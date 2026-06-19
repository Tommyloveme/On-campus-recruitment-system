# -*- coding: utf-8 -*-
"""认证接口：登录 / 退出 / 当前用户。"""
from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash

from campus.auth.decorators import login_required
from campus.db.connection import get_db
from campus.logging_util import log, who
from campus.services.candidates import user_dict

bp = Blueprint("auth", __name__)


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
