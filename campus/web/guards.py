# -*- coding: utf-8 -*-
"""HTTP 门禁：当前用户解析与访问装饰器。

管理员判定统一使用 campus.services.acl.is_admin（role=='admin' 或角色
bypass=true），全系统只有这一处实现，避免多套判定不一致。
"""
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
        from campus.services.acl import is_admin
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        if not is_admin(user):
            return jsonify({"error": "需要管理员权限"}), 403
        g.user = user
        return fn(*a, **kw)
    return wrapper


def module_read_required(module_key):
    """要求当前用户对模块具备读权限（admin 直通）。"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            from campus.services.acl import module_readable_for
            user = current_user()
            if not user:
                return jsonify({"error": "未登录"}), 401
            g.user = user
            if not module_readable_for(user, module_key):
                return jsonify({"error": f"无「{module_key}」模块的访问权限"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def module_write_required(module_key):
    """要求当前用户对模块具备写权限（admin 直通）。"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            from campus.services.acl import module_writable_for
            user = current_user()
            if not user:
                return jsonify({"error": "未登录"}), 401
            g.user = user
            if not module_writable_for(user, module_key):
                return jsonify({"error": f"无「{module_key}」模块的写入权限"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco
