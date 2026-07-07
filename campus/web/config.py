# -*- coding: utf-8 -*-
"""字段配置接口。"""
from flask import Blueprint, jsonify, request

from campus.core.settings import load_app_config
from campus.core.stage_config import build_config_response, load_stage_fields, load_stages_meta, validate_stage
from campus.web.guards import login_required

bp = Blueprint("config", __name__)


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
    return jsonify(resp)
