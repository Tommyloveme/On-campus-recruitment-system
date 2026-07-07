# -*- coding: utf-8 -*-
"""认证接口：登录 / 退出 / 账户选项 / 个人资料。

本系统不提供用户自助注册：所有账号、角色与权限均由系统管理员在
「用户管理」中创建并分配（详见 campus/web/users.py）。
"""
from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash

from campus.core.logging_util import log, who
from campus.db.connection import get_db
from campus.services.audit import add_log
from campus.services.users import (
    account_options_payload,
    builtin_fields,
    custom_fields,
    parse_extra,
    parse_user_profile_body,
    persist_user_columns,
    user_dict,
)
from campus.web.guards import login_required

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
    from campus.services.acl import is_admin
    d = user_dict(g.user)
    d["is_admin"] = is_admin(g.user)
    return jsonify(d)


@bp.put("/api/profile")
@login_required
def api_profile_update():
    body = request.get_json(force=True)
    db = get_db()
    user = g.user
    # 合并既有值后再校验
    merged = dict(body)
    for f in builtin_fields():
        k = f["key"]
        if k not in merged or merged.get(k) in (None, ""):
            merged[k] = user[k] if k in user.keys() else ""
    for f in custom_fields():
        k = f["key"]
        if k not in merged:
            merged[k] = parse_extra(user["extra"]).get(k, "")
    err, fields = parse_user_profile_body(merged)
    if err:
        return jsonify({"error": err}), 400

    persist_user_columns(db, user["id"], fields, user["role"], password=body.get("password"))
    add_log(user, "user", f"{fields['builtin'].get('display_name')} 更新了个人账户信息")
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    log.info("个人资料更新 %s", who(updated))
    return jsonify(user_dict(updated))
