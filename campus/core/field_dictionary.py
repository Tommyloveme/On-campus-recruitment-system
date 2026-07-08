# -*- coding: utf-8 -*-
"""原始数据预处理表字段字典（键 → 中文描述，唯一数据源）。

字典由现有配置自动汇总生成，不单独维护副本：
- config/stages/_common/fields.json 与各阶段 fields.json（键、中文名、类型）；
- config/master_import/<page>/field_mappings.json 的 ui_label
  （load_stage_fields 已把主数据映射字段并入并覆盖标签）。

因此新增/改名字段只需改上述 JSON，字典与各页面表格配置随之自动更新。
GET /api/field-dictionary 供前端「各子标签表格显示配置」取全量键与描述。
"""
from campus.core.stage_config import load_stage_fields, load_stages_meta


def field_dictionary():
    """全量字段字典：[{key, label, type, path, legacy_key, stages, options}]。"""
    from campus.db.field_store import load_field_registry
    reg = load_field_registry()
    entries = {}
    order = []
    for stage in load_stages_meta():
        for f in load_stage_fields(stage["key"]):
            key = f["key"]
            if key not in entries:
                meta = (reg.get("fields") or {}).get(f.get("legacy_key", key), {})
                entries[key] = {
                    "key": key,
                    "legacy_key": f.get("legacy_key", key),
                    "path": f.get("path") or ".".join(meta.get("path") or []),
                    "label": f.get("label", key),
                    "type": f.get("type", "text"),
                    "options": f.get("options") or [],
                    "stages": [],
                }
                order.append(key)
            entries[key]["stages"].append(stage["key"])
    return [entries[k] for k in order]


def field_label_map():
    """key -> 中文描述（日志、导出、表格配置等统一取此映射）。"""
    return {e["key"]: e["label"] for e in field_dictionary()}
