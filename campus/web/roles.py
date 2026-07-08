# -*- coding: utf-8 -*-
"""角色（权限模板）管理接口（仅系统管理员）。

角色定义持久化到 config/roles.json；新增/编辑/删除角色会写回该文件。
"""
from flask import Blueprint, g, jsonify, request

from campus.core.roles_store import (
    create_role,
    delete_role,
    role_log_level,
    role_is_builtin,
    roles_payload,
    update_role,
)
from campus.db.connection import get_db
from campus.services.audit import add_log
from campus.web.guards import admin_required

bp = Blueprint("roles", __name__)


@bp.get("/api/roles")
@admin_required
def api_roles_list():
    return jsonify({"roles": roles_payload()})


@bp.post("/api/roles")
@admin_required
def api_role_create():
    b = request.get_json(force=True)
    key = (b.get("key") or "").strip()
    label = (b.get("label") or "").strip()
    perms = b.get("perms") or {}
    bypass = bool(b.get("bypass"))
    try:
        r = create_role(key, label, perms=perms, bypass=bypass,
                        interview_positions=b.get("interview_positions"),
                        log_level=b.get("log_level"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    add_log(g.user, "permission", f"{g.user['display_name']} 新增了角色「{label}」（{key}）", module="permissions", level=1)
    get_db().commit()
    return jsonify({"ok": True, "role": r})


@bp.put("/api/roles/<key>")
@admin_required
def api_role_update(key):
    b = request.get_json(force=True)
    try:
        r = update_role(
            key,
            label=b.get("label"),
            perms=b.get("perms"),
            bypass=b.get("bypass"),
            interview_positions=b.get("interview_positions"),
            log_level=b.get("log_level"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if "log_level" in b or "bypass" in b:
        db = get_db()
        db.execute("UPDATE users SET log_level=? WHERE role=?", (role_log_level(key), key))
    add_log(g.user, "permission", f"{g.user['display_name']} 编辑了角色「{r['label']}」（{key}）", module="permissions", level=1)
    get_db().commit()
    return jsonify({"ok": True, "role": r})


@bp.delete("/api/roles/<key>")
@admin_required
def api_role_delete(key):
    if role_is_builtin(key):
        return jsonify({"error": "内置角色不可删除"}), 400
    try:
        delete_role(key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    add_log(g.user, "permission", f"{g.user['display_name']} 删除了角色（{key}）", module="permissions", level=1)
    get_db().commit()
    return jsonify({"ok": True})
