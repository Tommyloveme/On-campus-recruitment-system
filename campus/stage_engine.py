# -*- coding: utf-8 -*-
"""主数据表导入与流程阶段判定引擎。"""
import fnmatch
import json
import os
from datetime import datetime

from campus.config_loader import get_stage_meta, load_stages_meta
from campus.settings import BASE_DIR

MASTER_IMPORT_DIR = os.path.join(BASE_DIR, "config", "master_import")


def load_master_import_config(page="registration"):
    """按页面目录加载拆分后的主数据导入配置。"""
    page_dir = os.path.join(MASTER_IMPORT_DIR, page)
    index_path = os.path.join(page_dir, "index.json")
    if not os.path.exists(index_path):
        raise ValueError(f"主数据导入配置不存在: {page}")

    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    sources = []
    for key in index.get("source_keys", []):
        src_path = os.path.join(page_dir, "sources", f"{key}.json")
        with open(src_path, encoding="utf-8") as f:
            sources.append(json.load(f))

    rules_path = os.path.join(page_dir, "stage_rules.json")
    with open(rules_path, encoding="utf-8") as f:
        stage_rules = json.load(f)

    cfg = dict(index)
    cfg["sources"] = sources
    cfg["stage_rules"] = stage_rules
    return cfg


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
    for val in col_cfg.get("match_patterns", []):
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


def _value_matches(expected, actual):
    actual = str(actual or "").strip()
    if expected == "*":
        return bool(actual)
    if "*" in expected or "?" in expected:
        return (fnmatch.fnmatch(actual, expected)
                or fnmatch.fnmatch(actual.lower(), expected.lower()))
    return actual == expected


def _rule_matches(data, rule):
    fields = rule.get("fields") or []
    values = rule.get("values") or []
    if len(fields) != len(values):
        return False
    for fk, expected in zip(fields, values):
        actual = data.get(fk, "")
        if not _value_matches(expected, actual):
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


def merge_candidate_data(old, incoming, overwrite_empty_only=False):
    """合并导入数据到已有候选人 JSON。"""
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


def _strip_internal_fields(data):
    return {k: v for k, v in data.items() if not k.startswith("_")}


def resolve_group_id(data, cfg, groups_list):
    """从行数据解析新建候选人所属分组。"""
    gm = cfg.get("group_mapping") or {}
    field_key = gm.get("field_key", "_group_name")
    raw = str(data.get(field_key, "") or "").strip()
    name_to_id = {g["name"]: g["id"] for g in groups_list}

    if raw:
        if raw in name_to_id:
            return name_to_id[raw]
        for g in groups_list:
            if _text_match(raw, g["name"]):
                return g["id"]
        for g in groups_list:
            for pat in gm.get("match_patterns", []):
                if _text_match(pat, g["name"]) and (_text_match(pat, raw) or raw in g["name"]):
                    return g["id"]

    fallback = gm.get("fallback", "first")
    if fallback == "first" and groups_list:
        return groups_list[0]["id"]
    return None


def build_global_candidate_index(db):
    """全局索引：电话 / 姓名 -> 候选人记录（跨分组）。"""
    by_phone, by_name = {}, {}
    for row in db.execute("SELECT * FROM candidates").fetchall():
        data = json.loads(row["data"])
        if data.get("phone") and data["phone"] not in by_phone:
            by_phone[data["phone"]] = row
        if data.get("name") and data["name"] not in by_name:
            by_name[data["name"]] = row
    return by_phone, by_name


def apply_master_rows(rows_data, db, cfg, can_edit_fn, user, groups_list):
    """全局主表导入：跨分组匹配，按权限更新/新建。"""
    created = updated = skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_phone, by_name = build_global_candidate_index(db)

    for data in rows_data:
        if not data.get("name"):
            skipped += 1
            continue

        compute_current_stage(data, cfg)
        match = None
        if data.get("phone"):
            match = by_phone.get(data["phone"])
        if not match:
            match = by_name.get(data["name"])

        if match:
            group_id = match["group_id"]
            if not can_edit_fn(user, group_id):
                skipped += 1
                continue
            old = json.loads(match["data"])
            merged = merge_candidate_data(old, data)
            compute_current_stage(merged, cfg)
            if merged != old:
                db.execute(
                    "UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), now, match["id"]),
                )
                updated += 1
                match = db.execute("SELECT * FROM candidates WHERE id=?", (match["id"],)).fetchone()
                d = json.loads(match["data"])
                if d.get("phone"):
                    by_phone[d["phone"]] = match
                if d.get("name"):
                    by_name[d["name"]] = match
        else:
            group_id = resolve_group_id(data, cfg, groups_list)
            if not group_id or not can_edit_fn(user, group_id):
                skipped += 1
                continue
            payload = _strip_internal_fields(data)
            cur = db.execute(
                "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
                (group_id, json.dumps(payload, ensure_ascii=False), now, now),
            )
            row = db.execute("SELECT * FROM candidates WHERE id=?", (cur.lastrowid,)).fetchone()
            if payload.get("phone"):
                by_phone[payload["phone"]] = row
            if payload.get("name"):
                by_name[payload["name"]] = row
            created += 1
    return created, updated, skipped
