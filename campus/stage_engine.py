# -*- coding: utf-8 -*-
"""流程阶段判定引擎（实现见 campus.stage_routing）。"""
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
from campus.stage_routing import (
    compute_current_stage,
    stage_label_map,
    validate_stage_rules,
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
    "stage_label_map",
    "validate_stage_rules",
]


def run_dual_master_refresh(db, cfg, can_edit_fn, user):
    return _run_dual_master_refresh(db, cfg, can_edit_fn, user, compute_current_stage)
