# -*- coding: utf-8 -*-
"""候选人流程阶段判定：条件字段均来自 Application*.xlsx / 候选人管理*.xlsx 映射列。

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
from campus.domain.rule_engine import build_context_resolver, evaluate, validate_condition

# 判定规则中允许出现的字段 = 主数据 Excel 映射字段（不含内部 _ 前缀）
_ROUTING_FIELD_CACHE = None
_ALIAS_CACHE = None

MANUAL_STAGE_KEY = "manual_stage"


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
        if not _value_matches(expected, data.get(fk, "")):
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

    known_stages = {s["key"] for s in load_stages_meta()}
    manual = str(data.get(MANUAL_STAGE_KEY) or "").strip()
    if manual in known_stages:
        data[field_key] = manual
        return manual

    ctx_tables = {"预处理表": data, "candidates": data}
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
            stage = rule["stage"]
            data[field_key] = stage
            return stage
    data[field_key] = "registration"
    return "registration"


def stage_label_map():
    return {s["key"]: s.get("short_label") or s["label"] for s in load_stages_meta()}


def stage_order_map():
    return {s["key"]: s.get("order", 0) for s in load_stages_meta()}


def ordered_stage_keys():
    return [s["key"] for s in load_stages_meta()]
