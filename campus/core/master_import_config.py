# -*- coding: utf-8 -*-
"""主数据表导入配置加载（config/master_import/<page>/）。

只负责读取与组装 JSON 配置，不做 Excel 解析与数据库写入
（那部分在 campus.services.master_import）。放在 core 层是为了让
domain 层的阶段判定（stage_routing）也能读取字段映射而不依赖服务层。
"""
import json
import os

from campus.core.settings import BASE_DIR

MASTER_IMPORT_DIR = os.path.join(BASE_DIR, "config", "master_import")


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
