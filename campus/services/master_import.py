# -*- coding: utf-8 -*-
"""主数据表导入：配置加载、Excel 解析、按电话合并写入、字段锁定。"""
import copy
import fnmatch
import json
import os
import re
from datetime import datetime

from campus.config_loader import get_stage_meta, load_stages_meta
from campus.settings import BASE_DIR

MASTER_IMPORT_DIR = os.path.join(BASE_DIR, "config", "master_import")


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def load_field_mappings(page_dir, index):
    fname = index.get("field_mappings_file", "field_mappings.json")
    path = os.path.join(page_dir, fname)
    if not os.path.exists(path):
        return {"fields": [], "sources": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mapping_columns_for_source(field_mappings, source_key):
    cols = []
    for fm in field_mappings.get("fields", []):
        src_col = (fm.get("sources") or {}).get(source_key)
        if not src_col:
            continue
        col = dict(src_col)
        col.setdefault("match_patterns", [])
        col["field_key"] = fm["field_key"]
        if not col.get("excel_column"):
            col["excel_column"] = fm.get("ui_label") or fm["field_key"]
        cols.append(col)
    return cols


def apply_field_mappings_to_sources(sources, field_mappings):
    for src in sources:
        src_key = src.get("key")
        mapped = _mapping_columns_for_source(field_mappings, src_key)
        mapped_keys = {c["field_key"] for c in mapped}
        extra = [c for c in src.get("columns", []) if c.get("field_key") not in mapped_keys]
        for c in extra:
            c.setdefault("match_patterns", [])
        src["columns"] = mapped + extra
    return sources


def locked_fields_from_mappings(field_mappings):
    locked = []
    for fm in field_mappings.get("fields", []):
        if fm.get("lock_on_import") and fm.get("field_key"):
            locked.append(fm["field_key"])
    return locked


def master_field_ui_map(field_mappings):
    """field_key -> ui_label（空字符串表示界面不可见）。"""
    result = {}
    for fm in field_mappings.get("fields", []):
        key = fm.get("field_key")
        if not key:
            continue
        if "ui_label" in fm:
            result[key] = (fm.get("ui_label") or "").strip()
    return result


def _build_sources(page_dir, index, field_mappings):
    fm_sources = field_mappings.get("sources") or {}
    legacy_patterns = index.get("file_patterns") or {}
    file_patterns = {}
    sources = []
    for key in index.get("source_keys", []):
        base = {}
        src_path = os.path.join(page_dir, "sources", f"{key}.json")
        if os.path.exists(src_path):
            with open(src_path, encoding="utf-8") as f:
                base = json.load(f)
        fm_src = fm_sources.get(key) or {}
        src = {
            "key": key,
            "label": fm_src.get("label") or base.get("label", key),
            "description": fm_src.get("description") or base.get("description", ""),
            "storage_name": fm_src.get("storage_name") or base.get("storage_name", f"{key}.xlsx"),
            "sheet_name": fm_src.get("sheet_name", base.get("sheet_name", "")),
            "sheet_index": int(fm_src.get("sheet_index", base.get("sheet_index", 0))),
            "columns": base.get("columns", []),
        }
        pattern = fm_src.get("file_pattern") or base.get("file_pattern") or legacy_patterns.get(key, "*")
        file_patterns[key] = pattern
        sources.append(src)
    apply_field_mappings_to_sources(sources, field_mappings)
    return sources, file_patterns


def load_master_import_config(page="registration"):
    page_dir = os.path.join(MASTER_IMPORT_DIR, page)
    index_path = os.path.join(page_dir, "index.json")
    if not os.path.exists(index_path):
        raise ValueError(f"主数据导入配置不存在: {page}")

    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    field_mappings = load_field_mappings(page_dir, index)
    sources, file_patterns = _build_sources(page_dir, index, field_mappings)

    rules_path = os.path.join(page_dir, "stage_rules.json")
    with open(rules_path, encoding="utf-8") as f:
        stage_rules = json.load(f)

    cfg = dict(index)
    cfg["sources"] = sources
    cfg["stage_rules"] = stage_rules
    cfg["field_mappings"] = field_mappings
    cfg["file_patterns"] = file_patterns
    cfg["registration_locked_fields"] = (
        index.get("registration_locked_fields") or locked_fields_from_mappings(field_mappings)
    )
    return cfg


def registration_locked_fields(cfg=None):
    cfg = cfg or load_master_import_config()
    return list(cfg.get("registration_locked_fields") or
                locked_fields_from_mappings(cfg.get("field_mappings") or {}))


# ---------------------------------------------------------------------------
# Excel 解析
# ---------------------------------------------------------------------------

def _cell_str(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _text_match(pattern, text):
    if not pattern or text is None:
        return False
    text = str(text).strip()
    if not text:
        return False
    if "*" in pattern or "?" in pattern:
        return (fnmatch.fnmatch(text, pattern)
                or fnmatch.fnmatch(text.lower(), pattern.lower()))
    return pattern == text or pattern.lower() == text.lower()


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
    """未在映射中配置的 Excel 列：按表头中文转拼音生成 field_key。"""
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
    base, n = key, 1
    while key in used_keys:
        key = f"{base}_{n}"
        n += 1
    used_keys.add(key)
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
        if idx < len(raw_row):
            data[key] = _cell_str(raw_row[idx])
    return data


def _select_workbook_sheet(wb, source_cfg, source_label=""):
    label = source_label or source_cfg.get("label") or source_cfg.get("key") or "Excel"
    name = (source_cfg.get("sheet_name") or "").strip()
    if name:
        if name not in wb.sheetnames:
            raise ValueError(
                f"「{label}」中未找到工作表「{name}」，当前工作表：{', '.join(wb.sheetnames)}"
            )
        return wb[name]
    idx = int(source_cfg.get("sheet_index", 0))
    if idx < 0 or idx >= len(wb.sheetnames):
        raise ValueError(
            f"「{label}」工作表索引 {idx} 无效，当前共 {len(wb.sheetnames)} 个工作表"
        )
    return wb[wb.sheetnames[idx]]


def parse_excel_file(path, source_cfg):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    sheet = _select_workbook_sheet(wb, source_cfg)
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    col_map = parse_master_header(source_cfg, rows[0])
    return [row_to_data(source_cfg, col_map, raw) for raw in rows[1:]]


# ---------------------------------------------------------------------------
# 数据合并
# ---------------------------------------------------------------------------

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
    """主数据写入 DB：锁定字段以导入为准；其余字段可合并不冲突的值。"""
    cfg = cfg or load_master_import_config()
    reg_locked = registration_locked_fields(cfg)
    merged = dict(old)
    locked = list(old.get("_master_locked_fields") or [])

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
        merged["_master_locked_fields"] = locked
        merged["_master_imported"] = True

    from campus.services.candidates import delivery_date_from_resume_id

    delivery = delivery_date_from_resume_id(merged.get("resume_id") or incoming.get("resume_id"))
    if delivery:
        merged["delivery_time"] = delivery
    merged["registration_status"] = "已投递"
    return merged


def join_master_rows(app_rows, mgmt_rows, join_key="resume_id"):
    """关联双表后按电话再合并；无 join_key 但有电话的行也会保留。"""
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

    no_phone = [r for r in merged if not str(r.get("phone") or "").strip()]
    with_phone = merge_rows_by_phone([r for r in merged if str(r.get("phone") or "").strip()])
    return with_phone + no_phone


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


def apply_master_rows(rows_data, db, cfg, can_edit_fn, user, compute_stage_fn):
    from campus.services.candidates import (
        insert_candidate_row,
        normalize_candidate_phone,
        update_candidate_row,
    )

    created = updated = skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_phone = build_global_candidate_index(db)

    for data in rows_data:
        phone = normalize_candidate_phone(data.get("phone"))
        if not phone:
            skipped += 1
            continue
        data["phone"] = phone
        if not data.get("name"):
            skipped += 1
            continue

        compute_stage_fn(data, cfg)
        match = by_phone.get(phone)

        if match:
            if not can_edit_fn(user):
                skipped += 1
                continue
            old = json.loads(match["data"])
            merged = merge_master_import_data(old, data, cfg)
            compute_stage_fn(merged, cfg)
            if merged != old:
                update_candidate_row(db, match["id"], merged, ts=now)
                updated += 1
                match = db.execute("SELECT * FROM candidates WHERE id=?", (match["id"],)).fetchone()
                by_phone[phone] = match
        else:
            if not can_edit_fn(user):
                skipped += 1
                continue
            payload = merge_master_import_data({}, data, cfg)
            cid = insert_candidate_row(db, payload, group_id=None, ts=now)
            row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
            by_phone[phone] = row
            created += 1
    return created, updated, skipped


def run_dual_master_refresh(db, cfg, can_edit_fn, user, compute_stage_fn):
    from campus.services.master_import_store import both_files_ready, get_stored_files, load_meta, save_meta

    page = cfg.get("page", "registration")
    if not both_files_ready(page, cfg):
        raise ValueError("请先上传 Application*.xlsx 与 候选人管理*.xlsx 两个文件")

    files = get_stored_files(page, cfg)
    join_key = cfg.get("join_key", "resume_id")
    source_map = {s["key"]: s for s in cfg["sources"]}

    app_rows = parse_excel_file(files["application"]["path"], source_map["application"])
    mgmt_rows = parse_excel_file(files["candidate_mgmt"]["path"], source_map["candidate_mgmt"])
    rows_data = join_master_rows(app_rows, mgmt_rows, join_key)

    created, updated, skipped = apply_master_rows(
        rows_data, db, cfg, can_edit_fn, user, compute_stage_fn)

    meta = load_meta(page)
    meta["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta["last_refresh_stats"] = {
        "created": created, "updated": updated, "skipped": skipped,
        "application_rows": len(app_rows), "candidate_mgmt_rows": len(mgmt_rows),
        "merged_rows": len(rows_data),
    }
    save_meta(page, meta)
    return created, updated, skipped, meta["last_refresh_stats"]
