# -*- coding: utf-8 -*-
"""页面细粒度特性注册表（子标签/按钮级权限的唯一数据源）。

每个模块除 v/r/w/m 四个粗粒度权限外，还可按「特性」细化管控：
- kind=tab：页面内子标签是否可见（如 日志、数据看板）；
- kind=button：页面内按钮是否可见（如 新增、导出、批量删除、手动流转）。

默认全部允许；管理员在 权限管理 → 细粒度 中按 用户×模块 显式关闭。
存储：module_acl.perm_features（JSON，{feature_key: 0|1}，未出现=默认允许）。
"""
from campus.core.stage_config import stage_keys

_STAGE_COMMON = [
    {"key": "tab_logs", "label": "日志子标签", "kind": "tab"},
    {"key": "tab_dashboard", "label": "数据看板子标签", "kind": "tab"},
    {"key": "btn_export_excel", "label": "导出Excel按钮", "kind": "button"},
]

_REGISTRATION_EXTRA = [
    {"key": "btn_add", "label": "新增候选人按钮", "kind": "button"},
    {"key": "btn_master_import", "label": "主数据表导入按钮", "kind": "button"},
    {"key": "btn_batch_delete", "label": "批量删除按钮", "kind": "button"},
    {"key": "btn_export_resume", "label": "导出简历按钮", "kind": "button"},
]

_TRANSITION_EXTRA = [
    {"key": "btn_stage_transition", "label": "手动流转按钮", "kind": "button"},
]

_TRANSITION_STAGES = {"approval", "salary", "offer", "contract_signing"}


def module_features(module_key):
    """某模块可配置的细粒度特性列表（非阶段模块返回空）。"""
    if module_key not in stage_keys():
        return []
    feats = list(_STAGE_COMMON)
    if module_key == "registration":
        feats += _REGISTRATION_EXTRA
    if module_key in _TRANSITION_STAGES:
        feats += _TRANSITION_EXTRA
    return feats


def feature_keys(module_key):
    return [f["key"] for f in module_features(module_key)]
