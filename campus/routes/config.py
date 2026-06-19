# -*- coding: utf-8 -*-
"""字段配置接口。"""
from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.auth.permissions import GLOBAL_VIEW_ROLES
from campus.config_loader import (
    build_config_response,
    get_stage_meta,
    load_stage_fields,
    load_stages_meta,
    save_group_visible,
    validate_stage,
)
from campus.db.connection import get_db
from campus.logging_util import log, who
from campus.services.audit import add_log
from campus.services.candidates import group_name_map
from campus.settings import load_app_config

bp = Blueprint("config", __name__)


@bp.get("/api/config")
@login_required
def api_config():
    if g.user["role"] in GLOBAL_VIEW_ROLES:
        group_id = request.args.get("group_id", type=int)
    else:
        group_id = g.user["group_id"]
    stage = request.args.get("stage")
    if stage:
        try:
            validate_stage(stage)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        resp = {
            "stage": stage,
            "fields": load_stage_fields(stage, group_id),
            "group_id": group_id,
            "stages": load_stages_meta(),
            "app": {**load_app_config().get("ui", {}),
                    "interview": load_app_config().get("interview", {})},
        }
    else:
        resp = build_config_response(group_id)
        resp["app"] = load_app_config().get("ui", {})
        resp["app"]["interview"] = load_app_config().get("interview", {})
    return jsonify(resp)


@bp.put("/api/config")
@login_required
def api_config_update():
    body = request.get_json(force=True)
    stage = body.get("stage")
    if not stage:
        return jsonify({"error": "请指定阶段 stage"}), 400
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    updates = {f["key"]: f for f in body.get("fields", [])}

    if g.user["role"] == "admin":
        group_id = body.get("group_id")
    elif g.user["role"] == "group_admin":
        group_id = g.user["group_id"]
        if not group_id:
            return jsonify({"error": "您未归属任何分组"}), 400
    else:
        return jsonify({"error": "无配置权限"}), 403

    log.debug("字段配置更新 %s stage=%s group_id=%s keys=%s",
              who(g.user), stage, group_id, list(updates.keys()))
    if group_id:
        path_fields = load_stage_fields(stage, group_id)
        visible_map = {}
        for f in path_fields:
            visible_map[f["key"]] = f.get("visible", True)
        for key, u in updates.items():
            if "visible" in u:
                visible_map[key] = bool(u["visible"])
        save_group_visible(stage, group_id, visible_map)
        gname = group_name_map().get(group_id, "")
        stage_label = get_stage_meta(stage)["label"]
        add_log(g.user, "config",
                f"{g.user['display_name']} 调整了「{gname}」{stage_label}的字段显示配置",
                group_id=group_id)
    else:
        return jsonify({"error": "全局字段定义请直接编辑 config/stages/ 下的 JSON 文件"}), 400
    get_db().commit()
    log.info("字段配置已保存 %s stage=%s scope=%s", who(g.user), stage, group_id)
    return jsonify({"fields": load_stage_fields(stage, group_id), "stage": stage, "group_id": group_id})
