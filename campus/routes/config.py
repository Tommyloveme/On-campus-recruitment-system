# -*- coding: utf-8 -*-
"""字段配置接口。"""
from flask import Blueprint, jsonify, request

from campus.auth.decorators import login_required
from campus.config_loader import build_config_response, load_stage_fields, load_stages_meta, validate_stage
from campus.settings import load_app_config

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
                    "interview": load_app_config().get("interview", {})},
        }
    else:
        resp = build_config_response()
        resp["app"] = load_app_config().get("ui", {})
        resp["app"]["interview"] = load_app_config().get("interview", {})
    return jsonify(resp)
