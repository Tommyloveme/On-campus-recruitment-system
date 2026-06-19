# -*- coding: utf-8 -*-
"""认证接口：登录 / 退出 / 注册 / 个人资料。"""
import json
import sqlite3

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from campus.auth.decorators import login_required
from campus.db.connection import get_db, now_str
from campus.logging_util import log, who
from campus.services.audit import add_log
from campus.services.users import (
    default_register_job_roles,
    normalize_job_roles,
    parse_job_roles,
    parse_user_profile_body,
    register_options_payload,
    reserved_accounts,
    user_dict,
)
from campus.settings import APP_CONFIG

bp = Blueprint("auth", __name__)


@bp.get("/api/register/options")
def api_register_options():
    return jsonify(register_options_payload())


@bp.post("/api/register")
def api_register():
    body = request.get_json(force=True)
    username = (body.get("employee_id") or body.get("username") or "").strip()
    if username in reserved_accounts():
        return jsonify({"error": "系统管理员固定账号不可用于注册"}), 403

    err, fields = parse_user_profile_body(body, require_employee_id=True)
    if err:
        return jsonify({"error": err}), 400

    username = fields["employee_id"]

    password = body.get("password") or APP_CONFIG["security"]["default_password"]
    if not password:
        return jsonify({"error": "密码不能为空"}), 400

    job_roles = normalize_job_roles(body.get("job_roles") or default_register_job_roles())
    if not job_roles:
        return jsonify({"error": "请至少选择一个业务角色"}), 400

    group_id = None
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, "
            "supervisor, department, dept_level2, dept_level3, job_roles, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (username, fields["display_name"], generate_password_hash(password), "editor", group_id,
             fields["supervisor"], fields["department"], fields["dept_level2"], fields["dept_level3"],
             json.dumps(job_roles, ensure_ascii=False), now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "该工号已注册"}), 400
    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    add_log(user, "user", f"{fields['display_name']} 完成了账号注册（工号 {username}）")
    db.commit()
    log.info("用户注册成功 username=%s roles=%s ip=%s", username, job_roles, request.remote_addr)
    return jsonify({"ok": True, "username": username})


@bp.post("/api/login")
def api_login():
    body = request.get_json(force=True)
    username = body.get("username", "")
    user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], body.get("password", "")):
        log.warning("登录失败 username=%s ip=%s", username, request.remote_addr)
        return jsonify({"error": "用户名或密码错误"}), 401
    session["uid"] = user["id"]
    log.info("登录成功 %s ip=%s", who(user), request.remote_addr)
    return jsonify(user_dict(user))


@bp.post("/api/logout")
def api_logout():
    uid = session.get("uid")
    if uid:
        u = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if u:
            log.info("退出登录 %s", who(u))
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/me")
@login_required
def api_me():
    return jsonify(user_dict(g.user))


@bp.put("/api/profile")
@login_required
def api_profile_update():
    body = request.get_json(force=True)
    err, fields = parse_user_profile_body(body)
    if err:
        return jsonify({"error": err}), 400

    db = get_db()
    user = g.user
    keys = user.keys() if hasattr(user, "keys") else []
    job_roles = parse_job_roles(user["job_roles"] if "job_roles" in keys else None)
    if not job_roles:
        job_roles = list(default_register_job_roles())

    db.execute(
        "UPDATE users SET display_name=?, supervisor=?, department=?, dept_level2=?, dept_level3=? WHERE id=?",
        (fields["display_name"], fields["supervisor"], fields["department"],
         fields["dept_level2"], fields["dept_level3"], user["id"]),
    )
    if body.get("password"):
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(body["password"]), user["id"]),
        )
    add_log(user, "user", f"{fields['display_name']} 更新了个人账户信息")
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    log.info("个人资料更新 %s", who(updated))
    return jsonify(user_dict(updated))
