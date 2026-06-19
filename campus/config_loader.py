# -*- coding: utf-8 -*-
"""阶段与字段配置加载（高内聚：所有配置读取逻辑集中于此）。"""
import copy
import json
import os

from campus.settings import BASE_DIR

CONFIG_DIR = os.path.join(BASE_DIR, "config")
STAGES_PATH = os.path.join(CONFIG_DIR, "stages.json")
STAGES_DIR = os.path.join(CONFIG_DIR, "stages")
COMMON_STAGE = "_common"


def load_stages_meta():
    """读取阶段元数据列表（按 order 排序）。"""
    with open(STAGES_PATH, encoding="utf-8") as f:
        stages = json.load(f)["stages"]
    return sorted(stages, key=lambda s: s["order"])


def stage_keys():
    return [s["key"] for s in load_stages_meta()]


def get_stage_meta(stage_key):
    for s in load_stages_meta():
        if s["key"] == stage_key:
            return s
    return None


def validate_stage(stage_key):
    if stage_key not in stage_keys():
        raise ValueError(f"未知阶段: {stage_key}")
    return stage_key


def _stage_fields_path(stage_key):
    return os.path.join(STAGES_DIR, stage_key, "fields.json")


def _load_raw_fields(stage_key):
    path = _stage_fields_path(stage_key)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("fields", [])


def group_config_path(stage_key, group_id):
    """分组级字段显示配置路径（各阶段独立）。"""
    return os.path.join(STAGES_DIR, stage_key, f"fields_group_{group_id}.json")


def load_stage_fields(stage_key, group_id=None):
    """加载某阶段的完整字段列表 = 公共字段 + 阶段字段，并应用分组 visible 覆盖。"""
    validate_stage(stage_key)
    common = _load_raw_fields(COMMON_STAGE)
    stage = _load_raw_fields(stage_key)
    fields = copy.deepcopy(common + stage)

    # 非登记阶段：公共身份字段默认只读（登记阶段可编辑全部）
    if stage_key != "registration":
        for f in fields:
            if f["key"] in {x["key"] for x in common}:
                f["editable"] = False

    if group_id:
        path = group_config_path(stage_key, group_id)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                visible_map = json.load(f).get("visible", {})
            for field in fields:
                if field["key"] in visible_map:
                    field["visible"] = bool(visible_map[field["key"]])
    return fields


def load_all_fields(group_id=None):
    """加载全部阶段字段（去重，按阶段顺序合并）。"""
    seen = set()
    merged = []
    for stage in load_stages_meta():
        for f in load_stage_fields(stage["key"], group_id):
            if f["key"] not in seen:
                seen.add(f["key"])
                merged.append(copy.deepcopy(f))
    return merged


def save_stage_fields(stage_key, fields):
    """保存阶段专属字段（不含公共字段）。"""
    validate_stage(stage_key)
    common_keys = {f["key"] for f in _load_raw_fields(COMMON_STAGE)}
    stage_fields = [f for f in fields if f["key"] not in common_keys]
    path = _stage_fields_path(stage_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f) if os.path.exists(path) else {"comment": "", "fields": []}
    cfg["fields"] = stage_fields
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def save_common_fields(fields):
    path = _stage_fields_path(COMMON_STAGE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f) if os.path.exists(path) else {"comment": "", "fields": []}
    cfg["fields"] = fields
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def save_group_visible(stage_key, group_id, visible_map):
    path = group_config_path(stage_key, group_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "comment": f"阶段「{stage_key}」分组 {group_id} 的字段显示配置",
        "visible": visible_map,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def importable_fields(stage_key, group_id=None):
    return [f for f in load_stage_fields(stage_key, group_id) if f.get("importable")]


def editable_fields(stage_key, group_id=None):
    return [f for f in load_stage_fields(stage_key, group_id) if f.get("editable")]


def field_labels(stage_key=None, group_id=None):
    """字段 key -> label 映射。"""
    if stage_key:
        fields = load_stage_fields(stage_key, group_id)
    else:
        fields = load_all_fields(group_id)
    return {f["key"]: f["label"] for f in fields}


def match_import_header(field, header):
    """表头匹配：excel_column、label，以及 excel_aliases。"""
    if header == field.get("excel_column") or header == field.get("label"):
        return True
    return header in field.get("excel_aliases", [])


def build_config_response(group_id=None):
    """构建 /api/config 完整响应。"""
    from campus.stage_engine import load_master_import_config
    stages = load_stages_meta()
    stage_fields = {s["key"]: load_stage_fields(s["key"], group_id) for s in stages}
    try:
        master = load_master_import_config("registration")
    except (ValueError, OSError, json.JSONDecodeError):
        master = {"sources": [], "current_stage_field": "current_stage", "global_import": True}
    return {
        "stages": stages,
        "stage_fields": stage_fields,
        "group_id": group_id,
        "master_import": {
            "page": master.get("page", "registration"),
            "sources": [{"key": s["key"], "label": s["label"], "description": s.get("description", "")}
                        for s in master.get("sources", [])],
            "current_stage_field": master.get("current_stage_field", "current_stage"),
            "global_import": bool(master.get("global_import", True)),
        },
    }
