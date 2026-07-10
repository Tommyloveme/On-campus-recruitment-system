# -*- coding: utf-8 -*-
"""阶段与字段配置加载（高内聚：所有阶段/字段配置读取逻辑集中于此）。

配置目录对应关系（加字段/加阶段只改 JSON，无需改代码或数据库）：
- config/stages.json                   阶段清单与顺序（load_stages_meta）
- config/stages/_common/fields.json    全阶段公共字段
- config/stages/<stage>/fields.json    各阶段业务字段（load_stage_fields）
- config/stages/<stage>/display.json   表格列可见/可编辑（UI 列配置）

消费方：campus/web/*（接口校验与序列化）、campus/domain/stage_routing.py
（阶段判定）、campus/db/field_store.py（字段注册表生成）、前端 /api/config。
新增阶段还需在 campus/core/modules.py 登记模块（权限门禁用）。
"""
import copy
import json
import os

from campus.core.settings import BASE_DIR

CONFIG_DIR = os.path.join(BASE_DIR, "config")
STAGES_PATH = os.path.join(CONFIG_DIR, "stages.json")
STAGES_DIR = os.path.join(CONFIG_DIR, "stages")
COMMON_STAGE = "_common"


#: stages.json 解析缓存（mtime 失效）：阶段判定每行都要读阶段列表，
#: 万级导入时逐行读盘解析是明显热点
_STAGES_META_CACHE = {"stamp": None, "stages": None}


def _apply_flow_numbering(stage):
    """为流程阶段生成带编号的展示标签（供侧栏、列表、导出等使用）。"""
    code = str(stage.get("flow_code") or "").strip()
    if not code:
        return stage
    short = stage.get("short_label") or stage.get("label") or stage["key"]
    label = stage.get("label") or short
    stage["numbered_short_label"] = f"{code}-{short}"
    stage["numbered_label"] = f"{code}-{label}"
    return stage


def load_stages_meta():
    """读取阶段元数据列表（按 order 排序，带 mtime 缓存）。"""
    try:
        stamp = os.path.getmtime(STAGES_PATH)
    except OSError:
        stamp = None
    if _STAGES_META_CACHE["stages"] is None or _STAGES_META_CACHE["stamp"] != stamp:
        with open(STAGES_PATH, encoding="utf-8") as f:
            stages = json.load(f)["stages"]
        enriched = [_apply_flow_numbering(dict(s)) for s in stages]
        _STAGES_META_CACHE["stages"] = sorted(enriched, key=lambda s: s["order"])
        _STAGES_META_CACHE["stamp"] = stamp
    return [dict(s) for s in _STAGES_META_CACHE["stages"]]


def stage_numbered_label_map():
    """stage_key -> numbered_short_label（无 flow_code 时回退 short_label）。"""
    out = {}
    for s in load_stages_meta():
        out[s["key"]] = s.get("numbered_short_label") or s.get("short_label") or s.get("label") or s["key"]
    return out


def stage_numbered_full_label_map():
    """stage_key -> numbered_label（页面标题等完整名称）。"""
    out = {}
    for s in load_stages_meta():
        out[s["key"]] = s.get("numbered_label") or s.get("label") or s["key"]
    return out


def nav_label_for_module(key, base_label):
    """侧栏导航标签：流程阶段带编号，看板/反馈等保持原名。"""
    skip = {
        "data_board", "admin_board", "feedback",
        "overview", "charts", "permissions", "op_logs", "backups",
        "recruit_flow", "offer_strategy",
    }
    if key in skip:
        return base_label
    full = stage_numbered_full_label_map().get(key)
    if full:
        return full
    numbered = stage_numbered_label_map().get(key)
    return numbered or base_label


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


def _load_stage_display_overrides(stage_key):
    path = os.path.join(STAGES_DIR, stage_key, "display.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_stage_table_config(stage_key):
    """阶段表格 UI 配置：列顺序（仅影响网页表格）、左侧冻结列数（含勾选列）、
    默认排序，以及 UI 专属列 ui_columns。

    ui_columns 为仅存在于界面的附加列（不进候选人 data），每项
    {key, label, format: text|number|date}；取值同步存储于总表 data_hub
    （source='ui'，按简历编号关联）。
    """
    display = _load_stage_display_overrides(stage_key)
    default_sort = display.get("default_sort") or {}
    sort_dir = default_sort.get("dir", "asc")
    ui_columns = []
    for c in display.get("ui_columns") or []:
        if not c.get("key"):
            continue
        ui_columns.append({
            "key": str(c["key"]),
            "label": str(c.get("label") or c["key"]),
            "format": c.get("format", "text"),
        })
    from campus.db.field_store import legacy_to_storage
    return {
        "column_order": [legacy_to_storage(k) for k in (display.get("column_order") or [])],
        "frozen_column_count": int(display.get("frozen_column_count") or 0),
        "pre_resume_columns": [legacy_to_storage(k) for k in (display.get("pre_resume_columns") or [])],
        "ui_columns": ui_columns,
        "default_sort": {
            "key": legacy_to_storage(default_sort.get("key", "")),
            "dir": -1 if str(sort_dir).lower() in ("desc", "descending", "-1") else 1,
        } if default_sort.get("key") else None,
    }


def _registration_hidden_field_keys(display=None):
    """登记页：主数据映射中从三层部门到入职风险（含）的字段不在网页展示（保留登记核心列）。"""
    display = display or _load_stage_display_overrides("registration")
    hide_range = display.get("hide_field_range") or {}
    hide_from = hide_range.get("from", "dept_level3")
    hide_through = hide_range.get("through", "onboard_risk")
    keep_visible = set(display.get("keep_visible_in_range") or [])
    keep_visible.update({
        "sourcer", "sourcer_dept", "interface_person", "interface_dept",
        "registration_source", "registration_source_custom",
    })
    extra_hidden = set(display.get("hidden_keys") or [])
    extra_hidden.update({
        "physical_exam_time", "physical_exam_done", "onboard_booked", "onboard_booked_time",
    })
    try:
        from campus.core.master_import_config import load_master_import_config
        fields = (load_master_import_config("registration").get("field_mappings") or {}).get("fields", [])
        keys = [f["field_key"] for f in fields]
        start = keys.index(hide_from)
        end = keys.index(hide_through)
        hidden = {k for k in keys[start:end + 1] if not k.startswith("_") and k not in keep_visible}
        hidden |= extra_hidden
        return hidden
    except (ValueError, ImportError, OSError, json.JSONDecodeError):
        return extra_hidden


def _apply_registration_hidden_fields(fields, display=None):
    hidden = _registration_hidden_field_keys(display)
    if not hidden:
        return fields
    for field in fields:
        if field["key"] in hidden:
            field["visible"] = False
    return fields


def _apply_display_policy(fields, display, stage_key):
    """按 display.json 的 visible/editable 白名单覆盖；未列出默认不可见、不可编辑。"""
    from campus.db.field_store import legacy_to_storage
    visible_map = display.get("visible")
    editable_map = display.get("editable")
    has_policy = visible_map is not None or editable_map is not None
    if not has_policy and not display:
        for field in fields:
            field["visible"] = False
            field["editable"] = False
        return fields
    for field in fields:
        leg = field.get("legacy_key") or field["key"]
        k = field["key"]
        sk = legacy_to_storage(leg)
        if visible_map is not None:
            vis = visible_map.get(leg, visible_map.get(sk, visible_map.get(k, False)))
            field["visible"] = bool(vis)
        if editable_map is not None:
            ed = editable_map.get(leg, editable_map.get(sk, editable_map.get(k, False)))
            field["editable"] = bool(ed)
        elif visible_map is not None:
            field["editable"] = False
    return fields


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

    display = _load_stage_display_overrides(stage_key)
    fields = _apply_display_policy(fields, display, stage_key)

    if group_id:
        path = group_config_path(stage_key, group_id)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                visible_map = json.load(f).get("visible", {})
            for field in fields:
                if field["key"] in visible_map:
                    field["visible"] = bool(visible_map[field["key"]])

    fields = _apply_master_import_field_rules(fields)
    # 主数据映射可能注入新字段，再次应用 display 白名单
    fields = _apply_display_policy(fields, display, stage_key)

    if stage_key == "registration":
        fields = _apply_registration_hidden_fields(fields, display)
    return _apply_storage_keys(fields)


def _apply_storage_keys(fields):
    """字段 key 转为数据库中文 storage_key，并附带 legacy_key / path 供配置引用。"""
    from campus.db.field_store import legacy_to_storage, load_field_registry
    reg = load_field_registry()
    for f in fields:
        leg = f.get("key") or ""
        f["legacy_key"] = leg
        meta = (reg.get("fields") or {}).get(leg, {})
        f["path"] = ".".join(meta.get("path") or [])
        f["key"] = legacy_to_storage(leg)
    return fields


def _apply_master_import_field_rules(fields):
    """按 field_mappings.json 的 ui_label 控制可见性/标签；lock_on_import 由 API 层拦截。"""
    try:
        from campus.core.master_import_config import load_master_import_config, master_field_ui_map
        cfg = load_master_import_config("registration")
        ui_map = master_field_ui_map(cfg.get("field_mappings") or {})
    except (ValueError, OSError, json.JSONDecodeError):
        return fields
    if not ui_map:
        return fields
    existing = {f["key"] for f in fields}
    for field in fields:
        if field["key"] not in ui_map:
            continue
        ui = ui_map[field["key"]]
        if ui:
            field["label"] = ui
        else:
            field["visible"] = False
    for key, ui in ui_map.items():
        if key.startswith("_") or not ui or key in existing:
            continue
        fields.append({
            "key": key,
            "label": ui,
            "type": "text",
            "visible": False,
            "editable": False,
            "importable": False,
        })
    return fields


def load_all_fields(group_id=None):
    """加载全部阶段字段（去重，按阶段顺序合并）。"""
    seen = set()
    merged = []
    for stage in load_stages_meta():
        for f in load_stage_fields(stage["key"]):
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
    from campus.core.master_import_config import load_master_import_config
    stages = load_stages_meta()
    stage_fields = {s["key"]: load_stage_fields(s["key"]) for s in stages}
    try:
        master = load_master_import_config("registration")
    except (ValueError, OSError, json.JSONDecodeError):
        master = {"sources": [], "current_stage_field": "current_stage", "global_import": True}
    return {
        "stages": stages,
        "stage_fields": stage_fields,
        "stage_table": {s["key"]: load_stage_table_config(s["key"]) for s in stages},
        "master_import": {
            "page": master.get("page", "registration"),
            "import_mode": master.get("import_mode", "dual_file"),
            "join_key": master.get("join_key", "resume_id"),
            "match_keys": master.get("match_keys", ["phone"]),
        "registration_locked_fields": master.get("registration_locked_fields", []),
        "field_mappings": {
            "fields": [
                {
                    "field_key": f.get("field_key"),
                    "ui_label": f.get("ui_label"),
                    "lock_on_import": f.get("lock_on_import", False),
                    "sources": list((f.get("sources") or {}).keys()),
                }
                for f in (master.get("field_mappings") or {}).get("fields", [])
            ],
        },
            "file_patterns": master.get("file_patterns", {}),
            "sources": [{
                "key": s["key"],
                "label": s["label"],
                "description": s.get("description", ""),
                "pattern": (master.get("file_patterns") or {}).get(s["key"], "*"),
            } for s in master.get("sources", [])],
            "current_stage_field": master.get("current_stage_field", "current_stage"),
            "global_import": bool(master.get("global_import", True)),
        },
    }
