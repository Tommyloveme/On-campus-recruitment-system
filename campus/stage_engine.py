# -*- coding: utf-8 -*-
"""流程阶段判定引擎；主数据导入实现见 campus.services.master_import。"""
import fnmatch

from campus.config_loader import load_stages_meta
from campus.services.master_import import (
    apply_master_rows,
    build_global_candidate_index,
    join_master_rows,
    load_master_import_config,
    merge_candidate_data,
    merge_master_import_data,
    parse_excel_file,
    registration_locked_fields,
    run_dual_master_refresh as _run_dual_master_refresh,
)

# 兼容旧 import 路径
from campus.services.master_import import (  # noqa: F401
    load_field_mappings,
    locked_fields_from_mappings,
    match_column,
)

__all__ = [
    "compute_current_stage",
    "load_master_import_config",
    "run_dual_master_refresh",
    "build_global_candidate_index",
    "merge_candidate_data",
    "merge_master_import_data",
    "parse_excel_file",
    "join_master_rows",
    "apply_master_rows",
    "registration_locked_fields",
]


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


def run_dual_master_refresh(db, cfg, can_edit_fn, user):
    return _run_dual_master_refresh(db, cfg, can_edit_fn, user, compute_current_stage)
