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
    """原始数据预处理表字段字典（中文 storage_key + 嵌套 path + legacy_key）。"""
    return jsonify({"fields": field_dictionary()})


@bp.get("/api/db/schema")
@login_required
def api_db_schema():
    """数据库表结构说明 + 字段嵌套注册表（外部配置用）。"""
    from campus.db.field_store import load_field_registry, load_table_registry, nested_view
    reg = load_field_registry()
    return jsonify({
        "tables": load_table_registry(),
        "field_registry": {
            "version": reg.get("version"),
            "paths": reg.get("paths"),
            "fields": reg.get("fields"),
            "internal_keys": reg.get("internal_keys"),
        },
        "nested_example": nested_view({"姓名": "示例", "电话": "13800000000"}),
    })


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
        cfg = load_app_config()
        resp = build_config_response()
        resp["app"] = {**cfg.get("ui", {})}
        resp["app"]["interview"] = cfg.get("interview", {})
        resp["app"]["user_profile"] = cfg.get("user_profile", {})
        logs_cfg = cfg.get("logs", {})
        resp["app"]["logs_page_size"] = logs_cfg.get("page_size", resp["app"].get("page_size", 15))
        resp["app"]["logs_page_size_options"] = logs_cfg.get(
            "page_size_options", resp["app"].get("page_size_options", [15, 30, 50, 100]))
        from campus.core.stage_flow import load_stage_flow
        from campus.services.acl import manual_transition_allowed
        flow = load_stage_flow()
        resp["stage_flow"] = {
            "stages": flow["stages"],
            "roles": flow["roles"],
            "can_transition": manual_transition_allowed(g.user),
        }
    return jsonify(resp)
