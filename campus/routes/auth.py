# -*- coding: utf-8 -*-
"""认证接口：登录 / 退出 / 账户选项 / 个人资料。

本系统不提供用户自助注册：所有账号、角色与权限均由系统管理员在
「用户管理」中创建并分配（详见 campus/routes/users.py）。
"""
from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from campus.auth.decorators import login_required
from campus.db.connection import get_db
from campus.logging_util import log, who
from campus.services.audit import add_log
from campus.services.users import (
    account_options_payload,
    default_job_roles,
    parse_job_roles,
    parse_user_profile_body,
    user_dict,
)

bp = Blueprint("auth", __name__)


@bp.get("/api/account/options")
def api_account_options():
    """公开接口：下发部门选项与可选业务角色（供个人资料、用户管理弹窗使用）。"""
    return jsonify(account_options_payload())


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
        job_roles = list(default_job_roles())

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
