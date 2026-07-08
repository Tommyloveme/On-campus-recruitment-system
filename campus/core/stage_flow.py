# -*- coding: utf-8 -*-
"""手动流转配置（config/stage_flow.json）加载。

Offer 策略各阶段支持指定角色手动把候选人切换到下一流程 / 退回上一流程，
或清除手动状态恢复按 stage_rules 自动判定。
"""
import json
import os

from campus.core.settings import BASE_DIR

STAGE_FLOW_PATH = os.path.join(BASE_DIR, "config", "stage_flow.json")

_DEFAULT = {
    "stages": ["approval", "salary", "offer", "contract_signing"],
    "roles": ["admin"],
}


def load_stage_flow():
    if not os.path.exists(STAGE_FLOW_PATH):
        return dict(_DEFAULT)
    with open(STAGE_FLOW_PATH, encoding="utf-8") as f:
        cfg = json.load(f).get("manual_transition") or {}
    return {
        "stages": list(cfg.get("stages") or _DEFAULT["stages"]),
        "roles": list(cfg.get("roles") or _DEFAULT["roles"]),
    }
