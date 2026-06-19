# -*- coding: utf-8 -*-
"""用户管理接口。"""
import json
import sqlite3

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from campus.auth.decorators import admin_required, login_required
from campus.auth.permissions import VALID_ROLES
from campus.db.connection import get_db, now_str
from campus.services.audit import add_log
from campus.services.users import normalize_job_roles, parse_job_roles
from campus.settings import APP_CONFIG

bp = Blueprint("users", __name__)


def _user_row_dict(row):
    d = dict(row)
    d["job_roles"] = parse_job_roles(d.get("job_roles"))
    return d


@bp.get("/api/users")
@login_required
def api_users():
    sql = ("SELECT u.id, u.username, u.display_name, u.role, u.supervisor, u.department, u.job_roles "
           "FROM users u")
    if g.user["role"] not in ("admin", "group_admin"):
        return jsonify({"error": "无用户管理权限"}), 403
    rows = get_db().execute(sql + " ORDER BY u.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["job_roles"] = parse_job_roles(d.get("job_roles"))
        out.append(d)
    return jsonify(out)


@bp.post("/api/users")
@login_required
def api_user_create():
    b = request.get_json(force=True)
    username = (b.get("username") or "").strip()
    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    password = b.get("password") or APP_CONFIG["security"]["default_password"]
    role = b.get("role", "editor")
    supervisor = (b.get("supervisor") or "").strip()
    department = (b.get("department") or "").strip()
    job_roles = normalize_job_roles(b.get("job_roles") or [])

    if g.user["role"] == "admin":
        if role not in VALID_ROLES:
            return jsonify({"error": "角色不合法"}), 400
    elif g.user["role"] == "group_admin":
        if role not in ("editor", "viewer"):
            return jsonify({"error": "组管理员只能添加组成员或只读账号"}), 403
    else:
        return jsonify({"error": "无添加用户权限"}), 403

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, job_roles, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (username, b.get("display_name") or username, generate_password_hash(password),
             role, None, supervisor, department,
             json.dumps(job_roles, ensure_ascii=False), now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "用户名已存在"}), 400
    add_log(g.user, "user", f"{g.user['display_name']} 创建了用户「{b.get('display_name') or username}」")
    db.commit()
    return jsonify({"ok": True})


@bp.put("/api/users/<int:uid>")
@admin_required
def api_user_update(uid):
    b = request.get_json(force=True)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    role = b.get("role", user["role"])
    if role not in VALID_ROLES:
        return jsonify({"error": "角色不合法"}), 400
    job_roles = normalize_job_roles(b.get("job_roles", parse_job_roles(user["job_roles"])))
    db.execute(
        "UPDATE users SET display_name=?, role=?, supervisor=?, department=?, job_roles=? WHERE id=?",
        (b.get("display_name", user["display_name"]), role,
         (b.get("supervisor") or user["supervisor"] or "").strip(),
         (b.get("department") or user["department"] or "").strip(),
         json.dumps(job_roles, ensure_ascii=False), uid),
    )
    if b.get("password"):
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(b["password"]), uid))
    add_log(g.user, "user", f"{g.user['display_name']} 更新了用户「{user['display_name']}」的信息")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/users/<int:uid>")
@admin_required
def api_user_delete(uid):
    if uid == g.user["id"]:
        return jsonify({"error": "不能删除自己"}), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    add_log(g.user, "user", f"{g.user['display_name']} 删除了用户「{user['display_name']}」")
    db.commit()
    return jsonify({"ok": True})
