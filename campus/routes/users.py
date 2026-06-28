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
from campus.services.users import (
    lookup_employee_by_username,
    normalize_job_roles,
    parse_job_roles,
    parse_user_profile_body,
    user_dict,
    user_dept_display,
    validate_registration_user_refs,
)
from campus.settings import APP_CONFIG

bp = Blueprint("users", __name__)


def _user_row_dict(row):
    return user_dict(row)


@bp.get("/api/users")
@login_required
def api_users():
    sql = ("SELECT u.id, u.username, u.display_name, u.role, u.supervisor, u.department, "
           "u.dept_level2, u.dept_level3, u.job_roles FROM users u")
    if g.user["role"] not in ("admin", "group_admin"):
        return jsonify({"error": "无用户管理权限"}), 403
    rows = get_db().execute(sql + " ORDER BY u.id").fetchall()
    return jsonify([_user_row_dict(r) for r in rows])


@bp.get("/api/users/check-registration-refs")
@login_required
def api_check_registration_refs():
    """校验拓源人、接口人工号是否已由系统管理员创建。"""
    sourcer = (request.args.get("sourcer") or "").strip()
    interface_person = (request.args.get("interface_person") or "").strip()
    err = validate_registration_user_refs(get_db(), sourcer, interface_person)
    return jsonify({"ok": not err, "error": err or ""})


@bp.get("/api/users/lookup-employee")
@login_required
def api_lookup_employee():
    """按工号查询用户姓名与部门（登记页部门展示）。"""
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"error": "工号不能为空"}), 400
    row = lookup_employee_by_username(get_db(), username)
    if not row:
        return jsonify({
            "found": False,
            "error": f"工号「{username}」尚未由系统管理员创建，请联系管理员添加账号",
        })
    d = user_dict(row)
    return jsonify({
        "found": True,
        "username": d["username"],
        "display_name": d["display_name"],
        "department": user_dept_display(row),
    })


@bp.post("/api/users")
@login_required
def api_user_create():
    b = request.get_json(force=True)
    username = (b.get("username") or "").strip()
    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    password = b.get("password") or APP_CONFIG["security"]["default_password"]
    role = b.get("role", "editor")
    job_roles = normalize_job_roles(b.get("job_roles") or [])

    if g.user["role"] == "admin":
        if role not in VALID_ROLES:
            return jsonify({"error": "角色不合法"}), 400
    elif g.user["role"] == "group_admin":
        if role not in ("editor", "viewer"):
            return jsonify({"error": "组管理员只能添加组成员或只读账号"}), 403
    else:
        return jsonify({"error": "无添加用户权限"}), 403

    profile_body = {
        "display_name": b.get("display_name") or username,
        "supervisor": b.get("supervisor"),
        "dept_level2": b.get("dept_level2"),
        "dept_level3": b.get("dept_level3"),
        "department": b.get("department"),
    }
    err, fields = parse_user_profile_body(profile_body)
    if err:
        return jsonify({"error": err}), 400

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, "
            "supervisor, department, dept_level2, dept_level3, job_roles, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (username, fields["display_name"], generate_password_hash(password),
             role, None, fields["supervisor"], fields["department"],
             fields["dept_level2"], fields["dept_level3"],
             json.dumps(job_roles, ensure_ascii=False), now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "用户名已存在"}), 400
    add_log(g.user, "user", f"{g.user['display_name']} 创建了用户「{fields['display_name']}」")
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

    profile_body = {
        "display_name": b.get("display_name", user["display_name"]),
        "supervisor": b.get("supervisor", user["supervisor"]),
        "dept_level2": b.get("dept_level2", user["dept_level2"] if "dept_level2" in user.keys() else ""),
        "dept_level3": b.get("dept_level3", user["dept_level3"] if "dept_level3" in user.keys() else ""),
        "department": b.get("department", user["department"]),
    }
    err, fields = parse_user_profile_body(profile_body)
    if err:
        return jsonify({"error": err}), 400

    db.execute(
        "UPDATE users SET display_name=?, role=?, supervisor=?, department=?, "
        "dept_level2=?, dept_level3=?, job_roles=? WHERE id=?",
        (fields["display_name"], role, fields["supervisor"], fields["department"],
         fields["dept_level2"], fields["dept_level3"],
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
