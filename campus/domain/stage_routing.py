# -*- coding: utf-8 -*-
"""候选人流程阶段判定：条件字段均来自 applicationProcessList*.xlsx / 候选人面试安排管理列表*.xlsx 映射列。

规则文件 config/master_import/<page>/stage_rules.json，两种规则格式并存：

1. 旧格式（等值/通配符，逐字段与）：
   {"priority": 90, "stage": "offer", "fields": ["offer_status"], "values": ["已发放"]}

2. 新格式（when 条件树，支持 与all/或any/非not、eq/contains/icontains/regex/
   wildcard/in/empty/not_empty/startswith/gt... 任意组合嵌套；字段名可写
   英文 field_key、Excel 中文列名或界面中文标签；table 可指定取数表）：
   {"priority": 90, "stage": "offer",
    "when": {"all": [
        {"field": "Offer状态", "op": "eq", "value": "已发放"},
        {"any": [
            {"field": "毕业院校", "op": "regex", "value": "(大学|学院)$"},
            {"field": "学历", "op": "in", "value": ["硕士", "博士"]}
        ]}
    ]}}

   table 可选值：预处理表（默认）/ 主数据原始表 / 手动原始表
   （调用方传入相应记录时生效；未传入时按预处理表取值）。

手动流转覆盖：data 中存在 manual_stage（Offer策略页手动切换流程写入）时，
优先使用该阶段，不再按规则计算。
"""
import fnmatch

from campus.core.master_import_config import (
    load_master_import_config,
    master_field_alias_map,
)
from campus.core.stage_config import load_stages_meta
from campus.db.field_store import field_get, field_set, legacy_to_storage, normalize_record
from campus.domain.rule_engine import build_context_resolver, evaluate, validate_condition

# 判定规则中允许出现的字段 = 主数据 Excel 映射字段（不含内部 _ 前缀）
_ROUTING_FIELD_CACHE = None
_ALIAS_CACHE = None

MANUAL_STAGE_KEY = "manual_stage"

#: 流程终止标记字段（值「是」时冻结在当前阶段）与终止前快照（内部键）
TERMINATED_FLAG_KEY = "process_terminated"
TERMINATED_SNAPSHOT_KEY = "_终止前状态"


def is_terminated(data):
    return str(field_get(data, TERMINATED_FLAG_KEY) or "").strip() == "是"

# Offer 策略各子阶段：须主管面通过后方可进入（自动判定与手动流转均校验）
OFFER_STRATEGY_STAGES = frozenset({"approval", "salary", "offer", "contract_signing", "onboarding"})


# 当前流程状态先使用稳定的序号 + 阶段名，实际阶段仍由规则条件组合判定。
STAGE_STATUS_LABELS = {
    "registration": "01-投递",
    "resume_screening": "02-简历筛选",
    "qualification": "03-资格审查",
    "commercial_secret": "04-商业秘密签署",
    "written_test": "05-笔试",
    "personality_test": "06-性格测评",
    "qualification_interview": "07-资格面试",
    "tech_interview": "08-技术面",
    "manager_interview": "09-主管面",
    "approval": "10-offer策略",
    "salary": "10-offer策略",
    "offer": "10-offer策略",
    "contract_signing": "10-offer策略",
    "onboarding": "10-offer策略",
}


def stage_status_label(stage, data=None):
    return STAGE_STATUS_LABELS.get(stage, stage_label_map().get(stage, stage))


def manager_interview_passed(data):
    """主管面是否已通过（预处理表字段 manager_interview_result）。"""
    return str(field_get(data, "manager_interview_result") or "").strip() == "通过"


def apply_offer_strategy_gate(stage, data):
    """Offer 策略门禁：主管面未通过时不得处于 Offer 策略任一子阶段。"""
    if stage in OFFER_STRATEGY_STAGES and not manager_interview_passed(data):
        return "manager_interview"
    # 自动判定一旦进入 Offer 策略，统一落到第一个流程「报批」；
    # 报批之后的谈薪/Offer/签约/入职由手动流转推进（manual_stage 覆盖）。
    if stage in OFFER_STRATEGY_STAGES:
        return "approval"
    return stage


def _routing_allowed_fields(cfg=None):
    global _ROUTING_FIELD_CACHE
    if _ROUTING_FIELD_CACHE is not None:
        return _ROUTING_FIELD_CACHE
    cfg = cfg or load_master_import_config()
    keys = set()
    for f in (cfg.get("field_mappings") or {}).get("fields", []):
        k = f.get("field_key") or ""
        if k and not k.startswith("_"):
            keys.add(k)
    keys.add(cfg.get("current_stage_field", "current_stage"))
    _ROUTING_FIELD_CACHE = keys
    return keys


def _field_aliases(cfg=None):
    """中文列名/界面标签 -> field_key（缓存，规则引擎按中文名取值用）。"""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    cfg = cfg or load_master_import_config()
    _ALIAS_CACHE = master_field_alias_map(cfg.get("field_mappings") or {})
    return _ALIAS_CACHE


def validate_stage_rules(cfg=None):
    """校验 stage_rules：旧格式字段须在 Excel 映射内；新格式 when 结构合法。"""
    cfg = cfg or load_master_import_config()
    allowed = _routing_allowed_fields(cfg)
    aliases = _field_aliases(cfg)
    errors = []
    for rule in (cfg.get("stage_rules") or {}).get("rules", []):
        tag = f"规则 priority={rule.get('priority')}"
        if rule.get("when") is not None:
            errors.extend(f"{tag} {e}" for e in validate_condition(rule["when"]))
            continue
        for fk in rule.get("fields") or []:
            if fk not in allowed and fk not in aliases:
                errors.append(f"{tag} 引用未知字段「{fk}」")
    return errors


def _value_matches(expected, actual):
    actual = str(actual or "").strip()
    if expected == "*":
        return bool(actual)
    if "*" in expected or "?" in expected:
        return (fnmatch.fnmatch(actual, expected)
                or fnmatch.fnmatch(actual.lower(), expected.lower()))
    return actual == expected


def _legacy_rule_matches(data, rule):
    fields = rule.get("fields") or []
    values = rule.get("values") or []
    if len(fields) != len(values):
        return False
    for fk, expected in zip(fields, values):
        if not _value_matches(expected, field_get(data, fk, "")):
            return False
    return True


def _rule_matches(data, rule, resolver):
    if rule.get("when") is not None:
        return evaluate(rule["when"], resolver)
    return _legacy_rule_matches(data, rule)


def compute_current_stage(data, cfg=None, tables=None):
    """根据 stage_rules.json 计算候选人当前流程阶段（优先级高者先匹配）。

    tables 可选：{"主数据原始表": {...}, "手动原始表": {...}}，供 when 条件
    的 table 指定取数；预处理表恒为 data 本身。
    manual_stage 存在且合法时直接采用（手动流转覆盖）。
    """
    cfg = cfg or load_master_import_config()
    field_key = cfg.get("current_stage_field", "current_stage")
    payload = normalize_record(data or {})
    if isinstance(data, dict):
        data.clear()
        data.update(payload)
    else:
        data = payload

    # 流程终止：冻结在终止时所处阶段，不再按规则/手动状态推进
    if is_terminated(data):
        stage = str(field_get(data, field_key) or "registration").strip() or "registration"
        field_set(data, field_key, stage)
        field_set(data, "process_status", "流程终止")
        return stage

    known_stages = {s["key"] for s in load_stages_meta()}
    manual = str(field_get(data, MANUAL_STAGE_KEY) or field_get(data, "_手动流程阶段") or "").strip()
    if manual in known_stages:
        field_set(data, field_key, manual)
        field_set(data, "process_status", stage_status_label(manual, data))
        return manual

    ctx_tables = {
        "预处理表": data, "candidates": data,
        "主数据原始表": data, "手动原始表": data,
    }
    for name, record in (tables or {}).items():
        if record is not None:
            ctx_tables[name] = record
    resolver = build_context_resolver(ctx_tables, "预处理表", alias_map=_field_aliases(cfg))

    rules = sorted(
        (cfg.get("stage_rules") or {}).get("rules", []),
        key=lambda r: r.get("priority", 0),
        reverse=True,
    )
    for rule in rules:
        if _rule_matches(data, rule, resolver):
            stage = apply_offer_strategy_gate(rule["stage"], data)
            field_set(data, field_key, stage)
            # 流程状态：简单显示“序号 + 当前流程”，实际 stage 仍由规则条件组合判定。
            field_set(data, "process_status", stage_status_label(stage, data))
            return stage
    field_set(data, field_key, "registration")
    field_set(data, "process_status", stage_status_label("registration", data))
    return "registration"


def stage_label_map():
    return {s["key"]: s.get("short_label") or s["label"] for s in load_stages_meta()}


def stage_order_map():
    return {s["key"]: s.get("order", 0) for s in load_stages_meta()}


def ordered_stage_keys():
    return [s["key"] for s in load_stages_meta()]
