# -*- coding: utf-8 -*-
"""主数据表导入：Excel 解析、按唯一键（应聘档案编号→手机号）合并、写入候选人。

配置加载在 campus.core.master_import_config；上传文件存储在
campus.services.master_import_store。
"""
import fnmatch
import json
import re
from datetime import datetime

from campus.core.master_import_config import (
    load_master_import_config,
    registration_locked_fields,
)
from campus.db.field_store import field_get, field_set, legacy_to_storage, normalize_record


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
    # read_only 流式解析：万行大表比常规模式快数倍且省内存
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = _select_workbook_sheet(wb, source_cfg)
        rows_iter = sheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if header is None:
            return []
        col_map = parse_master_header(source_cfg, header)
        return [row_to_data(source_cfg, col_map, raw) for raw in rows_iter]
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
    field_set(merged, "registration_status", "已投递")
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
    data = json.loads(row["data"])
    for i in row_identity(data, match_keys):
        index[i] = row


def apply_master_rows(rows_data, db, cfg, can_edit_fn, user, compute_stage_fn):
    from campus.services.candidates import (
        insert_candidate_row,
        normalize_candidate_phone,
        update_candidate_row,
    )

    from campus.core.master_import_config import master_field_label_map
    from campus.services.candidate_pipeline import record_master
    from campus.services.data_hub import SOURCE_MASTER, hub_resume_key, record_hub_fields

    created = updated = skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    match_keys = cfg.get("match_keys") or MATCH_KEYS_DEFAULT
    index = build_candidate_identity_index(db, match_keys)
    hub_labels = master_field_label_map(cfg.get("field_mappings") or {})
    hub_tab = cfg.get("page", "registration")
    user_name = user["display_name"] if user else ""

    for data in rows_data:
        data = normalize_record(dict(data))
        phone = normalize_candidate_phone(field_get(data, "phone"))
        if phone and not phone_looks_valid(phone):
            # 掩码号码（+86 XXXXXXXXXXX 等）不写入电话字段，避免撞唯一约束
            phone = ""
            field_set(data, "phone", "")
        elif phone:
            field_set(data, "phone", phone)
        # 需要姓名 + 至少一个身份键（应聘档案编号/电话）才能唯一化建档
        if not field_get(data, "name") or not row_identity(data, match_keys):
            skipped += 1
            continue

        compute_stage_fn(data, cfg)
        match = match_candidate(index, data, match_keys)

        can_edit = can_edit_fn(user)
        if not can_edit:
            skipped += 1
            continue

        old = json.loads(match["data"]) if match else None
        if match:
            merged = merge_master_import_data(old, data, cfg)
            compute_stage_fn(merged, cfg)
            changed = merged != old
        else:
            merged = None
            changed = True

        # 重复刷新时大部分行没有任何变化：跳过总表/原始表回写，
        # 否则每行数十个字段的 UPSERT 是重复导入的最大耗时点
        if changed:
            record_hub_fields(db, SOURCE_MASTER, hub_tab, hub_resume_key(data),
                              data, hub_labels, user_name)
            cn_labels = {hub_labels.get(k, k): v for k, v in data.items()
                         if not k.startswith("_")}
            raw_phone = phone or (normalize_candidate_phone(
                field_get(old, "phone")) if old else "")
            if raw_phone:
                record_master(db, raw_phone, data, labels=cn_labels, ts=now)

        if match:
            if changed:
                update_candidate_row(db, match["id"], merged, ts=now)
                updated += 1
                match = db.execute("SELECT * FROM candidates WHERE id=?", (match["id"],)).fetchone()
            _index_candidate(index, match, match_keys)
        else:
            payload = merge_master_import_data({}, data, cfg)
            cid = insert_candidate_row(db, payload, group_id=None, ts=now)
            row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
            _index_candidate(index, row, match_keys)
            created += 1
    return created, updated, skipped


def run_dual_master_refresh(db, cfg, can_edit_fn, user, compute_stage_fn=None):
    """读取全部已上传数据源，按唯一键（应聘档案编号→手机号）合并后刷新候选人。

    数据源顺序（index.json 的 source_keys）即合并优先级：靠前的表先入底，
    后续表只补空值，不覆盖冲突值。任一数据源就绪即可单独刷新。
    """
    from campus.domain.stage_routing import compute_current_stage
    from campus.services.master_import_store import both_files_ready, get_stored_files, load_meta, save_meta

    compute_stage_fn = compute_stage_fn or compute_current_stage

    page = cfg.get("page", "registration")
    if not both_files_ready(page, cfg):
        raise ValueError("请先上传主数据表（applicationProcessList*.xlsx / 候选人面试安排管理列表*.xlsx 任一）")

    files = get_stored_files(page, cfg)
    source_map = {s["key"]: s for s in cfg["sources"]}
    match_keys = cfg.get("match_keys") or MATCH_KEYS_DEFAULT

    all_rows = []
    per_source = {}
    for key in cfg.get("source_keys", []):
        info = files.get(key) or {}
        if info.get("ready") and info.get("path") and key in source_map:
            rows = parse_excel_file(info["path"], source_map[key])
            per_source[f"{key}_rows"] = len(rows)
            all_rows.extend(rows)
    rows_data = merge_rows_by_identity(all_rows, match_keys)

    created, updated, skipped = apply_master_rows(
        rows_data, db, cfg, can_edit_fn, user, compute_stage_fn)

    meta = load_meta(page)
    meta["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta["last_refresh_stats"] = {
        "created": created, "updated": updated, "skipped": skipped,
        "merged_rows": len(rows_data), **per_source,
    }
    save_meta(page, meta)
    return created, updated, skipped, meta["last_refresh_stats"]
