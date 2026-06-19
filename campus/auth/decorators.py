# -*- coding: utf-8 -*-
"""认证装饰器与当前用户。"""
from functools import wraps

from flask import g, jsonify, session

from campus.db.connection import get_db


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        g.user = user
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        if user["role"] != "admin":
            return jsonify({"error": "需要管理员权限"}), 403
        g.user = user
        return fn(*a, **kw)
    return wrapper
