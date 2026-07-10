# -*- coding: utf-8 -*-
"""主数据表导入：Excel 解析、按唯一键（应聘档案编号→手机号）合并、写入候选人。

配置加载在 campus.core.master_import_config；上传文件存储在
campus.services.master_import_store。

性能策略：
- Excel 多文件并行解析（ThreadPoolExecutor）
- 行级预处理（规范化/阶段判定/合并）多线程并行
- SQLite 写入保持单线程（WAL 下多写反而锁竞争），批量 executemany + 分段 commit
"""
import fnmatch
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from campus.core.logging_util import log
from campus.core.master_import_config import (
    load_master_import_config,
    registration_locked_fields,
)
from campus.core.settings import load_app_config
from campus.db.field_store import field_get, field_set, legacy_to_storage, normalize_record


def _import_tuning():
    cfg = (load_app_config().get("master_import") or {})
    cpu = os.cpu_count() or 4
    return {
        "parse_workers": max(1, int(cfg.get("parse_workers") or min(2, cpu))),
        "prepare_workers": max(1, int(cfg.get("prepare_workers") or min(4, cpu))),
        "write_batch_size": max(50, int(cfg.get("write_batch_size") or 300)),
    }


# ---------------------------------------------------------------------------
# Excel 解析
# ---------------------------------------------------------------------------

def _cell_str(v):
    """单元格转文本：日期统一 YYYY-MM-DD（带时分秒则保留），见 domain.dates。"""
    from campus.domain.dates import normalize_date_value
    if v is None:
        return ""
    if isinstance(v, datetime):
        return normalize_date_value(v)
    return normalize_date_value(str(v).strip())


#: 表头归一化：真实业务表为手输入，全/半角括号、冒号、横线与空白经常不一致
_HEADER_TRANS = str.maketrans({
    "（": "(", "）": ")", "：": ":", "－": "-", "—": "-", "　": "",
    " ": "", "\t": "", "\u00a0": "",
})


def _norm_header(s):
    return str(s or "").strip().translate(_HEADER_TRANS)


def _text_match(pattern, text):
    if not pattern or text is None:
        return False
    text = str(text).strip()
    if not text:
        return False
    if "*" in pattern or "?" in pattern:
        return (fnmatch.fnmatch(text, pattern)
                or fnmatch.fnmatch(text.lower(), pattern.lower())
                or fnmatch.fnmatch(_norm_header(text).lower(), _norm_header(pattern).lower()))
    if pattern == text or pattern.lower() == text.lower():
        return True
    # 手输表头容错：忽略全/半角与空白差异
    return _norm_header(pattern).lower() == _norm_header(text).lower()


def phone_looks_valid(phone):
    """真实号码判定：剔除掩码（如 +86 XXXXXXXXXXX）与占位符。"""
    v = re.sub(r"[+\s\-()]", "", str(phone or ""))
    return v.isdigit() and len(v) >= 6


def _column_patterns(col_cfg):
    seen = set()
    for key in ("excel_column", "field_key"):
        val = col_cfg.get(key)
        if val and val not in seen:
            seen.add(val)
            yield val
    for val in col_cfg.get("excel_aliases", []):
        if val and val not in seen:
            seen.add(val)
            yield val
    for val in col_cfg.get("match_patterns") or []:
        if val and val not in seen:
            seen.add(val)
            yield val


def match_column(col_cfg, header):
    if not header:
        return False
    for pattern in _column_patterns(col_cfg):
        if _text_match(pattern, header):
            return True
    return False


def excel_header_to_field_key(header, used_keys):
    """未在映射中配置的 Excel 列：直接使用表头原文作为字段键。

    中文表头 → 中文键；英文表头保持英文（不做转换）。仅压缩空白并去重。
    """
    key = re.sub(r"\s+", "", str(header or "").strip())
    if not key:
        key = "未命名列"
    base, n = key, 1
    while key in used_keys:
        key = f"{base}_{n}"
        n += 1
    used_keys.add(key)
    return key


def header_to_pinyin_key(header):
    """历史拼音键算法（仅存量数据迁移用，勿再用于新导入）。"""
    header = (header or "").strip()
    try:
        from pypinyin import lazy_pinyin, Style
        parts = lazy_pinyin(header, style=Style.NORMAL)
        key = "_".join(p for p in parts if p).lower()
    except ImportError:
        key = re.sub(r"[^\w]+", "_", header, flags=re.UNICODE).strip("_").lower()
    key = re.sub(r"_+", "_", key).strip("_")
    if not key:
        key = "col"
    if key[0].isdigit():
        key = f"col_{key}"
    return key


def parse_master_header(source_cfg, header_row, import_all_columns=True):
    headers = [_cell_str(h) for h in header_row]
    col_map = {}
    used_field_keys = set()
    for idx, h in enumerate(headers):
        if not h:
            continue
        for col in source_cfg["columns"]:
            if match_column(col, h):
                fk = col["field_key"]
                col_map[idx] = fk
                used_field_keys.add(fk)
                break
    if import_all_columns:
        for idx, h in enumerate(headers):
            if idx in col_map or not h:
                continue
            col_map[idx] = excel_header_to_field_key(h, used_field_keys)
    required = [c["field_key"] for c in source_cfg["columns"] if c.get("required")]
    for rk in required:
        if rk not in col_map.values():
            label = next(c["excel_column"] for c in source_cfg["columns"] if c["field_key"] == rk)
            raise ValueError(f"Excel 中未找到必填列「{label}」")
    return col_map


def row_to_data(source_cfg, col_map, raw_row):
    data = {}
    for idx, key in col_map.items():
        if idx >= len(raw_row):
            continue
        v = _cell_str(raw_row[idx])
        # 同一字段可能映射多列（主列 + 别名列），空列不覆盖已取到的值
        if v or key not in data:
            data[key] = v
    return data


def _select_workbook_sheet(wb, source_cfg, source_label=""):
    label = source_label or source_cfg.get("label") or source_cfg.get("key") or "Excel"
    name = (source_cfg.get("sheet_name") or "").strip()
    if name:
        if name in wb.sheetnames:
            return wb[name]
        # 兼容 Sheet / Sheet1 等命名差异：配置的工作表不存在时回退 sheet_index
        idx = int(source_cfg.get("sheet_index", 0))
        if 0 <= idx < len(wb.sheetnames):
            return wb[wb.sheetnames[idx]]
        raise ValueError(
            f"「{label}」中未找到工作表「{name}」，当前工作表：{', '.join(wb.sheetnames)}"
        )
    idx = int(source_cfg.get("sheet_index", 0))
    if idx < 0 or idx >= len(wb.sheetnames):
        raise ValueError(
            f"「{label}」工作表索引 {idx} 无效，当前共 {len(wb.sheetnames)} 个工作表"
        )
    return wb[wb.sheetnames[idx]]


def parse_excel_file(path, source_cfg):
    from openpyxl import load_workbook
    label = source_cfg.get("label") or source_cfg.get("key") or path
    log.info("主数据解析开始 source=%s path=%s", source_cfg.get("key"), path)
    # read_only 流式解析：万行大表比常规模式快数倍且省内存
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception:
        log.exception("主数据解析打开失败 source=%s path=%s", source_cfg.get("key"), path)
        raise ValueError(f"无法打开「{label}」，请确认文件为有效的 .xlsx")
    try:
        sheet = _select_workbook_sheet(wb, source_cfg)
        rows_iter = sheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if header is None:
            log.warning("主数据解析空表 source=%s", source_cfg.get("key"))
            return []
        col_map = parse_master_header(source_cfg, header)
        rows = [row_to_data(source_cfg, col_map, raw) for raw in rows_iter]
        log.info("主数据解析完成 source=%s rows=%d mapped_cols=%d",
                 source_cfg.get("key"), len(rows), len(col_map))
        return rows
    except ValueError:
        log.exception("主数据解析校验失败 source=%s", source_cfg.get("key"))
        raise
    except Exception:
        log.exception("主数据解析异常 source=%s", source_cfg.get("key"))
        raise ValueError(f"解析「{label}」失败，请检查表头与工作表配置")
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# 数据合并
# ---------------------------------------------------------------------------

#: 候选人唯一化匹配键优先级（可被 index.json 的 match_keys 覆盖）。
#: 一旦存在应聘档案编号，后续各流程数据都以它唯一化；否则退化到手机号。
MATCH_KEYS_DEFAULT = ["application_archive_id", "phone"]


def row_identity(data, match_keys=None):
    """按优先级提取一行数据的身份键列表 [(kind, value), ...]。"""
    from campus.services.candidates import normalize_candidate_phone

    out = []
    for k in (match_keys or MATCH_KEYS_DEFAULT):
        v = str(field_get(data, k) or "").strip()
        if k == "phone":
            v = normalize_candidate_phone(v)
            # 掩码/无效号码（如 +86 XXXXXXXXXXX）不能作为唯一化身份键
            if v and not phone_looks_valid(v):
                v = ""
        if v:
            out.append((k, v))
    return out


def merge_rows_by_identity(rows, match_keys=None):
    """按身份键（档案编号→电话）合并导入行；同一人多行合并为一行。

    没有任何身份键的行无法唯一化，直接丢弃。
    """
    index = {}
    merged = []
    for row in rows:
        ids = row_identity(row, match_keys)
        if not ids:
            continue
        target = next((index[i] for i in ids if i in index), None)
        if target is None:
            target = len(merged)
            merged.append(dict(row))
        else:
            merged[target] = merge_import_row_data(merged[target], row)
        for i in row_identity(merged[target], match_keys):
            index.setdefault(i, target)
    return merged


def merge_import_row_data(base, incoming):
    """合并两行导入数据：空值填充、相同保留、冲突不覆盖。"""
    merged = dict(base)
    for k, v in incoming.items():
        if k.startswith("_"):
            continue
        nv = str(v or "").strip()
        if not nv:
            continue
        ov = str(merged.get(k, "") or "").strip()
        if not ov:
            merged[k] = nv
    return merged


def merge_rows_by_phone(rows):
    from campus.services.candidates import normalize_candidate_phone

    by_phone, order = {}, []
    for row in rows:
        phone = normalize_candidate_phone(row.get("phone"))
        if not phone:
            continue
        row = dict(row)
        row["phone"] = phone
        if phone in by_phone:
            by_phone[phone] = merge_import_row_data(by_phone[phone], row)
        else:
            by_phone[phone] = row
            order.append(phone)
    return [by_phone[p] for p in order]


def merge_candidate_data(old, incoming, overwrite_empty_only=False):
    merged = dict(old)
    for k, v in incoming.items():
        if k.startswith("_"):
            continue
        if not v:
            continue
        if overwrite_empty_only:
            if not str(merged.get(k, "") or "").strip():
                merged[k] = v
        elif str(merged.get(k, "") or "") != v:
            merged[k] = v
    return merged


def merge_master_import_data(old, incoming, cfg=None):
    """主数据写入 DB：锁定字段以导入为准；其余字段可合并不冲突的值。

    old / incoming 一律先规范化为中文 storage_key；锁定字段列表也以
    中文键存储（_主数据锁定字段）。
    """
    cfg = cfg or load_master_import_config()
    reg_locked = [legacy_to_storage(k) for k in registration_locked_fields(cfg)]
    merged = normalize_record(dict(old or {}))
    incoming = normalize_record(dict(incoming or {}))
    locked = [legacy_to_storage(k)
              for k in (field_get(merged, "_master_locked_fields") or [])]

    for k in reg_locked:
        val = incoming.get(k)
        if val and str(val).strip():
            merged[k] = str(val).strip()
            if k not in locked:
                locked.append(k)

    for k, v in incoming.items():
        if k.startswith("_") or k in reg_locked:
            continue
        nv = str(v or "").strip()
        if not nv:
            continue
        ov = str(merged.get(k, "") or "").strip()
        if not ov:
            merged[k] = nv
        elif ov != nv:
            continue

    if locked:
        field_set(merged, "_master_locked_fields", locked)
        field_set(merged, "_master_imported", True)

    from campus.services.candidates import delivery_date_from_resume_id

    delivery = delivery_date_from_resume_id(
        field_get(merged, "application_archive_id") or field_get(incoming, "application_archive_id")
        or field_get(merged, "resume_id") or field_get(incoming, "resume_id"))
    if delivery:
        field_set(merged, "delivery_time", delivery)
    from campus.domain.stage_routing import sync_stage_action_status
    sync_stage_action_status(merged)
    return merged


def join_master_rows(app_rows, mgmt_rows, join_key="application_archive_id", match_keys=None):
    """双表按 join_key（默认应聘档案编号）关联，再按身份键优先级唯一化合并。"""
    mgmt_by_key = {}
    for row in mgmt_rows:
        key = str(row.get(join_key, "") or "").strip()
        if key:
            mgmt_by_key[key] = row

    merged = []
    seen_join_keys = set()

    for app_row in app_rows:
        combined = dict(app_row)
        jk = str(app_row.get(join_key, "") or "").strip()
        if jk and jk in mgmt_by_key:
            combined = merge_import_row_data(combined, mgmt_by_key[jk])
            seen_join_keys.add(jk)
        merged.append(combined)

    for jk, mgmt_row in mgmt_by_key.items():
        if jk in seen_join_keys:
            continue
        merged.append(dict(mgmt_row))

    for mgmt_row in mgmt_rows:
        jk = str(mgmt_row.get(join_key, "") or "").strip()
        if jk:
            continue
        if mgmt_row.get("name") or mgmt_row.get("phone"):
            merged.append(dict(mgmt_row))

    return merge_rows_by_identity(merged, match_keys)


# ---------------------------------------------------------------------------
# 写入数据库
# ---------------------------------------------------------------------------

def build_global_candidate_index(db):
    from campus.services.candidates import normalize_candidate_phone

    by_phone = {}
    for row in db.execute("SELECT * FROM candidates").fetchall():
        phone = normalize_candidate_phone(row["phone"] if "phone" in row.keys() else "")
        if not phone:
            data = json.loads(row["data"])
            phone = normalize_candidate_phone(data.get("phone"))
        if phone and phone not in by_phone:
            by_phone[phone] = row
    return by_phone


def build_candidate_identity_index(db, match_keys=None):
    """现有候选人的身份键索引 {(kind, value): row}，按 match_keys 优先。"""
    index = {}
    for row in db.execute("SELECT * FROM candidates").fetchall():
        data = json.loads(row["data"])
        for i in row_identity(data, match_keys):
            index.setdefault(i, row)
    return index


def match_candidate(index, data, match_keys=None):
    """按身份键优先级在索引中查找已有候选人行。"""
    for i in row_identity(data, match_keys):
        if i in index:
            return index[i]
    return None


def _index_candidate(index, row, match_keys=None):
    data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
    for i in row_identity(data, match_keys):
        index[i] = row


def _row_proxy(cid, data, phone=""):
    """轻量行对象，避免 insert/update 后再 SELECT。"""
    return {
        "id": cid,
        "data": json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data,
        "phone": phone or None,
    }


def _prepare_import_row(raw, match_keys, index, can_edit, compute_stage_fn, cfg):
    """单行预处理（可并行）：规范化、阶段判定、与库内记录合并。返回动作描述。"""
    from campus.services.candidates import normalize_candidate_phone

    data = normalize_record(dict(raw))
    phone = normalize_candidate_phone(field_get(data, "phone"))
    if phone and not phone_looks_valid(phone):
        phone = ""
        field_set(data, "phone", "")
    elif phone:
        field_set(data, "phone", phone)

    if not field_get(data, "name") or not row_identity(data, match_keys):
        return {"action": "skip", "reason": "no_id"}

    if not can_edit:
        return {"action": "skip", "reason": "no_perm"}

    compute_stage_fn(data, cfg)
    match = match_candidate(index, data, match_keys)
    if match:
        old = json.loads(match["data"]) if isinstance(match["data"], str) else dict(match["data"])
        merged = merge_master_import_data(old, data, cfg)
        compute_stage_fn(merged, cfg)
        if merged == old:
            return {"action": "noop", "match_id": match["id"], "data": data, "phone": phone}
        raw_phone = phone or normalize_candidate_phone(field_get(old, "phone") or "")
        return {
            "action": "update",
            "match_id": match["id"],
            "data": data,
            "merged": merged,
            "phone": phone,
            "raw_phone": raw_phone,
            "changed": True,
        }

    payload = merge_master_import_data({}, data, cfg)
    compute_stage_fn(payload, cfg)
    return {
        "action": "insert",
        "data": data,
        "merged": payload,
        "phone": phone,
        "raw_phone": phone,
        "changed": True,
    }


def _prepare_import_rows_parallel(rows_data, match_keys, index, can_edit,
                                  compute_stage_fn, cfg, workers, progress_cb=None):
    """多线程预处理全部导入行，保持原顺序；分块提交避免一次性创建过多 Future。"""
    total = len(rows_data)
    if total == 0:
        return []
    workers = max(1, min(workers, total))
    prepared = [None] * total

    if workers == 1:
        for i, raw in enumerate(rows_data):
            prepared[i] = _prepare_import_row(
                raw, match_keys, index, can_edit, compute_stage_fn, cfg)
            if progress_cb and ((i + 1) % max(1, total // 50) == 0 or i + 1 == total):
                pct = 35 + int(10 * (i + 1) / total)
                progress_cb(phase="prepare",
                            message=f"正在预处理 {i + 1}/{total}",
                            percent=min(45, pct), current=i + 1, total=total)
        return prepared

    log.info("主数据预处理并行 workers=%d rows=%d", workers, total)
    chunk = max(200, total // (workers * 8) or 200)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, total, chunk):
            end = min(total, start + chunk)
            futs = {
                pool.submit(
                    _prepare_import_row, rows_data[i], match_keys, index,
                    can_edit, compute_stage_fn, cfg): i
                for i in range(start, end)
            }
            for fut in as_completed(futs):
                i = futs[fut]
                prepared[i] = fut.result()
                done += 1
                if progress_cb and (done % max(1, total // 50) == 0 or done == total):
                    pct = 35 + int(10 * done / total)
                    progress_cb(phase="prepare",
                                message=f"正在预处理 {done}/{total}",
                                percent=min(45, pct), current=done, total=total)
    return prepared


def apply_master_rows(rows_data, db, cfg, can_edit_fn, user, compute_stage_fn,
                      progress_cb=None):
    from campus.services.candidates import (
        insert_candidate_row,
        normalize_candidate_phone,
        update_candidate_row,
    )

    from campus.core.master_import_config import master_field_label_map
    from campus.services.candidate_pipeline import record_master
    from campus.services.data_hub import SOURCE_MASTER, hub_resume_key, record_hub_fields

    tuning = _import_tuning()
    created = updated = skipped = 0
    skip_no_id = skip_no_perm = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    match_keys = cfg.get("match_keys") or MATCH_KEYS_DEFAULT
    index = build_candidate_identity_index(db, match_keys)
    hub_labels = master_field_label_map(cfg.get("field_mappings") or {})
    hub_tab = cfg.get("page", "registration")
    user_name = user["display_name"] if user else ""
    total = len(rows_data)
    can_edit = bool(can_edit_fn(user))
    log.info("主数据写入开始 rows=%d existing_index=%d prepare_workers=%d batch=%d",
             total, len(index), tuning["prepare_workers"], tuning["write_batch_size"])

    if progress_cb:
        progress_cb(phase="prepare", message="正在并行预处理…",
                    percent=35, current=0, total=total,
                    created=0, updated=0, skipped=0)

    # 导入期加速：放宽同步、加大页缓存（结束后由连接关闭自然恢复）
    try:
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute("PRAGMA temp_store = MEMORY")
        db.execute("PRAGMA cache_size = -64000")  # ~64MB
    except Exception:
        pass

    prepared = _prepare_import_rows_parallel(
        rows_data, match_keys, index, can_edit, compute_stage_fn, cfg,
        tuning["prepare_workers"], progress_cb=progress_cb)

    if progress_cb:
        progress_cb(phase="write", message="正在写入候选人…",
                    percent=45, current=0, total=total)

    batch_size = tuning["write_batch_size"]
    step = max(1, min(500, total // 100 or 1)) if total else 1

    for i, prep in enumerate(prepared, start=1):
        action = (prep or {}).get("action")
        if action == "skip":
            skipped += 1
            if prep.get("reason") == "no_id":
                skip_no_id += 1
            else:
                skip_no_perm += 1
        elif action == "noop":
            pass
        elif action == "update":
            data = prep["data"]
            merged = prep["merged"]
            record_hub_fields(db, SOURCE_MASTER, hub_tab, hub_resume_key(data),
                              data, hub_labels, user_name)
            raw_phone = prep.get("raw_phone") or ""
            if raw_phone:
                cn_labels = {hub_labels.get(k, k): v for k, v in data.items()
                             if not k.startswith("_")}
                record_master(db, raw_phone, data, labels=cn_labels, ts=now)
            update_candidate_row(db, prep["match_id"], merged, ts=now)
            updated += 1
            phone = prep.get("phone") or normalize_candidate_phone(
                field_get(merged, "phone") or "")
            _index_candidate(index, _row_proxy(prep["match_id"], merged, phone), match_keys)
        elif action == "insert":
            data = prep["data"]
            payload = prep["merged"]
            record_hub_fields(db, SOURCE_MASTER, hub_tab, hub_resume_key(data),
                              data, hub_labels, user_name)
            raw_phone = prep.get("raw_phone") or ""
            if raw_phone:
                cn_labels = {hub_labels.get(k, k): v for k, v in data.items()
                             if not k.startswith("_")}
                record_master(db, raw_phone, data, labels=cn_labels, ts=now)
            cid = insert_candidate_row(db, payload, group_id=None, ts=now)
            created += 1
            phone = prep.get("phone") or normalize_candidate_phone(
                field_get(payload, "phone") or "")
            _index_candidate(index, _row_proxy(cid, payload, phone), match_keys)

        if i % batch_size == 0:
            db.commit()

        if i % 5000 == 0 or i == total:
            log.info("主数据写入进度 %d/%d +%d ~%d skip%d",
                     i, total, created, updated, skipped)
        if progress_cb and (i % step == 0 or i == total):
            pct = 45 + int(50 * i / total) if total else 95
            progress_cb(phase="write",
                        message=f"正在写入候选人 {i}/{total}",
                        percent=min(95, pct), current=i, total=total,
                        created=created, updated=updated, skipped=skipped)

    db.commit()
    log.info("主数据写入完成 +%d ~%d skip%d (no_id=%d no_perm=%d)",
             created, updated, skipped, skip_no_id, skip_no_perm)
    return created, updated, skipped


def _parse_one_source(key, path, source_cfg):
    rows = parse_excel_file(path, source_cfg)
    return key, rows, source_cfg.get("label") or key


def run_dual_master_refresh(db, cfg, can_edit_fn, user, compute_stage_fn=None):
    """读取全部已上传数据源，按唯一键（应聘档案编号→手机号）合并后刷新候选人。

    合并优先级：Application 主表优先于面试安排管理表——两表同列且均有值时，
    保留 Application 主表内容，面试表仅补空。source_keys 顺序与此一致。
    """
    import time
    from campus.domain.stage_routing import compute_current_stage
    from campus.services.master_import_store import (
        both_files_ready, get_stored_files, load_meta, save_meta, save_progress,
    )

    compute_stage_fn = compute_stage_fn or compute_current_stage
    t0 = time.perf_counter()
    tuning = _import_tuning()

    page = cfg.get("page", "registration")
    if not both_files_ready(page, cfg):
        raise ValueError("请先上传主数据表（applicationProcessList*.xlsx / 候选人面试安排管理列表*.xlsx 任一）")

    def progress(**kw):
        save_progress(page, status="running", **kw)

    files = get_stored_files(page, cfg)
    source_map = {s["key"]: s for s in cfg["sources"]}
    match_keys = cfg.get("match_keys") or MATCH_KEYS_DEFAULT
    join_key = cfg.get("join_key") or "application_archive_id"
    source_keys = list(cfg.get("source_keys") or [])

    log.info("主数据刷新开始 page=%s sources=%s join_key=%s match_keys=%s parse_workers=%d",
             page, source_keys, join_key, match_keys, tuning["parse_workers"])
    progress(phase="start", message="开始刷新…", percent=1,
             current=0, total=0, created=0, updated=0, skipped=0, error=None)

    ready = []
    for key in source_keys:
        info = files.get(key) or {}
        if info.get("ready") and info.get("path") and key in source_map:
            ready.append((key, info["path"], source_map[key]))

    parsed = {}
    per_source = {}
    if not ready:
        raise ValueError("请先上传主数据表")

    progress(phase="parse", message="正在并行解析 Excel…", percent=5)
    workers = max(1, min(tuning["parse_workers"], len(ready)))
    try:
        if workers == 1:
            results = [_parse_one_source(k, p, s) for k, p, s in ready]
        else:
            log.info("主数据 Excel 并行解析 workers=%d files=%d", workers, len(ready))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_parse_one_source, k, p, s) for k, p, s in ready]
                results = [f.result() for f in futs]
    except Exception as e:
        log.exception("主数据刷新解析失败")
        save_progress(page, status="error", phase="parse",
                      message="解析失败", error=str(e), percent=10)
        raise

    for idx, (key, rows, label) in enumerate(results):
        parsed[key] = rows
        per_source[f"{key}_rows"] = len(rows)
        progress(phase="parse",
                 message=f"已解析「{label}」{len(rows)} 行",
                 percent=5 + int(25 * (idx + 1) / max(1, len(results))))

    progress(phase="merge", message="正在合并双表数据…", percent=30)

    # Application 主表优先：有双表时用 join（主表为底、面试表补空）；单表则直接唯一化
    primary = source_keys[0] if source_keys else "application"
    secondary_keys = [k for k in source_keys[1:] if k in parsed]
    if primary in parsed and secondary_keys:
        rows_data = list(parsed[primary])
        for sk in secondary_keys:
            # 逐表以主表为底合并，保证同列冲突时主表胜出
            rows_data = join_master_rows(
                rows_data, parsed[sk], join_key=join_key, match_keys=match_keys)
        log.info("主数据双表合并 primary=%s secondary=%s merged=%d",
                 primary, secondary_keys, len(rows_data))
    elif primary in parsed:
        rows_data = merge_rows_by_identity(parsed[primary], match_keys)
        log.info("主数据单表合并 source=%s merged=%d", primary, len(rows_data))
    else:
        # 仅上传了非主表（如仅面试表）
        all_rows = []
        for key in source_keys:
            all_rows.extend(parsed.get(key) or [])
        rows_data = merge_rows_by_identity(all_rows, match_keys)
        log.info("主数据非主表合并 sources=%s merged=%d", list(parsed), len(rows_data))

    progress(phase="merge", message=f"合并完成，共 {len(rows_data)} 条待写入",
             percent=35, total=len(rows_data))

    try:
        created, updated, skipped = apply_master_rows(
            rows_data, db, cfg, can_edit_fn, user, compute_stage_fn,
            progress_cb=progress)
    except Exception as e:
        log.exception("主数据写入失败 page=%s rows=%d", page, len(rows_data))
        save_progress(page, status="error", phase="write",
                      message="写入失败", error=str(e), percent=90)
        raise

    meta = load_meta(page)
    meta["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta["last_refresh_stats"] = {
        "created": created, "updated": updated, "skipped": skipped,
        "merged_rows": len(rows_data), **per_source,
        "parse_workers": tuning["parse_workers"],
        "prepare_workers": tuning["prepare_workers"],
    }
    save_meta(page, meta)
    elapsed = time.perf_counter() - t0
    save_progress(page, status="done", phase="done",
                  message=f"完成：新增 {created}，更新 {updated}"
                          + (f"，跳过 {skipped}" if skipped else ""),
                  percent=100, current=len(rows_data), total=len(rows_data),
                  created=created, updated=updated, skipped=skipped, error=None)
    log.info("主数据刷新完成 page=%s +%d ~%d skip%d merged=%d elapsed=%.1fs",
             page, created, updated, skipped, len(rows_data), elapsed)
    return created, updated, skipped, meta["last_refresh_stats"]
