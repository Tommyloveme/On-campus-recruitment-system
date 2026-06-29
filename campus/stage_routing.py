# -*- coding: utf-8 -*-
"""候选人流程阶段判定：条件字段均来自 Application*.xlsx / 候选人管理*.xlsx 映射列。"""
import fnmatch

from campus.config_loader import load_stages_meta
from campus.services.master_import import load_master_import_config

# 判定规则中允许出现的字段 = 主数据 Excel 映射字段（不含内部 _ 前缀）
_ROUTING_FIELD_CACHE = None


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


def validate_stage_rules(cfg=None):
    """校验 stage_rules 中引用的字段均在 Excel 映射内。"""
    cfg = cfg or load_master_import_config()
    allowed = _routing_allowed_fields(cfg)
    errors = []
    for rule in (cfg.get("stage_rules") or {}).get("rules", []):
        for fk in rule.get("fields") or []:
            if fk not in allowed:
                errors.append(f"规则 priority={rule.get('priority')} 引用未知字段「{fk}」")
    return errors


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
        if not _value_matches(expected, data.get(fk, "")):
            return False
    return True


def compute_current_stage(data, cfg=None):
    """根据 stage_rules.json 计算候选人当前流程阶段（优先级高者先匹配）。"""
    cfg = cfg or load_master_import_config()
    field_key = cfg.get("current_stage_field", "current_stage")
    rules = sorted(
        (cfg.get("stage_rules") or {}).get("rules", []),
        key=lambda r: r.get("priority", 0),
        reverse=True,
    )
    for rule in rules:
        if _rule_matches(data, rule):
            stage = rule["stage"]
            data[field_key] = stage
            return stage
    data[field_key] = "registration"
    return "registration"


def stage_label_map():
    return {s["key"]: s.get("short_label") or s["label"] for s in load_stages_meta()}


def stage_order_map():
    return {s["key"]: s.get("order", 0) for s in load_stages_meta()}
