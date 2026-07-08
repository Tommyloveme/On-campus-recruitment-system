# -*- coding: utf-8 -*-
"""字段配置接口。"""
from flask import Blueprint, g, jsonify, request

from campus.core.field_dictionary import field_dictionary
from campus.core.settings import load_app_config
from campus.core.stage_config import build_config_response, load_stage_fields, load_stages_meta, validate_stage
from campus.web.guards import login_required

bp = Blueprint("config", __name__)


@bp.get("/api/field-dictionary")
@login_required
def api_field_dictionary():
    """原始数据预处理表字段字典（键→中文描述，自动汇总自阶段/主数据配置）。"""
    return jsonify({"fields": field_dictionary()})


@bp.get("/api/config")
@login_required
def api_config():
    stage = request.args.get("stage")
    if stage:
        try:
            validate_stage(stage)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        resp = {
            "stage": stage,
            "fields": load_stage_fields(stage),
            "stages": load_stages_meta(),
            "app": {**load_app_config().get("ui", {}),
                    "interview": load_app_config().get("interview", {}),
                    "user_profile": load_app_config().get("user_profile", {})},
        }
    else:
        resp = build_config_response()
        resp["app"] = load_app_config().get("ui", {})
        resp["app"]["interview"] = load_app_config().get("interview", {})
        resp["app"]["user_profile"] = load_app_config().get("user_profile", {})
        from campus.core.stage_flow import load_stage_flow
        from campus.services.acl import manual_transition_allowed
        flow = load_stage_flow()
        resp["stage_flow"] = {
            "stages": flow["stages"],
            "roles": flow["roles"],
            "can_transition": manual_transition_allowed(g.user),
        }
    return jsonify(resp)
