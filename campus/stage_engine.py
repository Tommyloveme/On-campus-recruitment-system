# -*- coding: utf-8 -*-
"""主数据表导入与流程阶段判定引擎。"""
import json
import os
from datetime import datetime

from campus.config_loader import BASE_DIR, get_stage_meta, load_stages_meta

MASTER_IMPORT_PATH = os.path.join(BASE_DIR, "config", "master_import.json")


def load_master_import_config():
    with open(MASTER_IMPORT_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cell_str(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def match_column(col_cfg, header):
    if header == col_cfg.get("excel_column") or header == col_cfg.get("field_key"):
        return True
    return header in col_cfg.get("excel_aliases", [])


def parse_master_header(source_cfg, header_row):
    """表头行 -> {col_index: field_key}"""
    headers = [_cell_str(h) for h in header_row]
    col_map = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        for col in source_cfg["columns"]:
            if match_column(col, h):
                col_map[idx] = col["field_key"]
                break
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


def _rule_matches(data, rule):
    fields = rule.get("fields") or []
    values = rule.get("values") or []
    if len(fields) != len(values):
        return False
    for fk, expected in zip(fields, values):
        actual = str(data.get(fk, "") or "").strip()
        if expected == "*":
            if not actual:
                return False
        elif actual != expected:
            return False
    return True


def compute_current_stage(data, cfg=None):
    """根据 stage_rules 计算候选人当前流程阶段。"""
    cfg = cfg or load_master_import_config()
    field_key = cfg.get("current_stage_field", "current_stage")
    rules = sorted(cfg.get("stage_rules", {}).get("rules", []),
                   key=lambda r: r.get("priority", 0), reverse=True)
    for rule in rules:
        if _rule_matches(data, rule):
            stage = rule["stage"]
            data[field_key] = stage
            return stage
    data[field_key] = "registration"
    return "registration"


def stage_label_map():
    return {s["key"]: s.get("short_label") or s["label"] for s in load_stages_meta()}


def build_master_template(source_key):
    cfg = load_master_import_config()
    source = next((s for s in cfg["sources"] if s["key"] == source_key), None)
    if not source:
        raise ValueError(f"未知数据源: {source_key}")
    return [c["excel_column"] for c in source["columns"]]


def merge_candidate_data(old, incoming, overwrite_empty_only=False):
    """合并导入数据到已有候选人 JSON。"""
    merged = dict(old)
    for k, v in incoming.items():
        if not v:
            continue
        if overwrite_empty_only:
            if not str(merged.get(k, "") or "").strip():
                merged[k] = v
        elif str(merged.get(k, "") or "") != v:
            merged[k] = v
    return merged


def apply_master_rows(rows_data, group_id, db, existing_by_phone, existing_by_name):
    """批量应用主表行数据，返回 created, updated, skipped。"""
    created = updated = skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for data in rows_data:
        if not data.get("name"):
            skipped += 1
            continue
        compute_current_stage(data)
        match = None
        if data.get("phone"):
            match = existing_by_phone.get(data["phone"])
        if not match:
            match = existing_by_name.get(data["name"])
        if match:
            old = json.loads(match["data"])
            merged = merge_candidate_data(old, data)
            compute_current_stage(merged)
            if merged != old:
                db.execute(
                    "UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), now, match["id"]),
                )
                updated += 1
                match = db.execute("SELECT * FROM candidates WHERE id=?", (match["id"],)).fetchone()
                d = json.loads(match["data"])
                if d.get("phone"):
                    existing_by_phone[d["phone"]] = match
                existing_by_name[d.get("name", "")] = match
        else:
            cur = db.execute(
                "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
                (group_id, json.dumps(data, ensure_ascii=False), now, now),
            )
            row = db.execute("SELECT * FROM candidates WHERE id=?", (cur.lastrowid,)).fetchone()
            if data.get("phone"):
                existing_by_phone[data["phone"]] = row
            existing_by_name[data["name"]] = row
            created += 1
    return created, updated, skipped
