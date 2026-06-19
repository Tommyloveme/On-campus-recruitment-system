# -*- coding: utf-8 -*-
"""分组管理接口。"""
import os
import sqlite3

from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import admin_required, login_required
from campus.config_loader import group_config_path, load_stages_meta
from campus.db.connection import get_db, now_str
from campus.services.audit import add_log

bp = Blueprint("groups", __name__)


@bp.get("/api/groups")
@login_required
def api_groups():
    rows = get_db().execute(
        "SELECT g.*, (SELECT COUNT(*) FROM candidates c WHERE c.group_id=g.id) AS candidate_count "
        "FROM groups g ORDER BY g.id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/groups")
@admin_required
def api_group_create():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"error": "分组名不能为空"}), 400
    db = get_db()
    try:
        db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", (name, now_str()))
    except sqlite3.IntegrityError:
        return jsonify({"error": "分组名已存在"}), 400
    add_log(g.user, "group", f"{g.user['display_name']} 创建了分组「{name}」")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/groups/<int:gid>")
@admin_required
def api_group_delete(gid):
    db = get_db()
    row = db.execute("SELECT name FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "分组不存在"}), 404
    if db.execute("SELECT COUNT(*) AS c FROM candidates WHERE group_id=?", (gid,)).fetchone()["c"] > 0:
        return jsonify({"error": "该分组下仍有候选人，无法删除"}), 400
    db.execute("UPDATE users SET group_id=NULL WHERE group_id=?", (gid,))
    db.execute("DELETE FROM groups WHERE id=?", (gid,))
    for s in load_stages_meta():
        gpath = group_config_path(s["key"], gid)
        if os.path.exists(gpath):
            os.remove(gpath)
    add_log(g.user, "group", f"{g.user['display_name']} 删除了分组「{row['name']}」")
    db.commit()
    return jsonify({"ok": True})
