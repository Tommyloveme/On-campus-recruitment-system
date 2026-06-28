# -*- coding: utf-8 -*-
"""用户管理接口（纯分组授权模型，已取消业务角色）。

系统仅区分「系统管理员」(admin) 与普通用户 (user)。主管/部门等信息仍绑定
用户但移至二级菜单维护。新建用户自动加入「默认分组」获得基线权限。
"""
import json
import sqlite3

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from campus.auth.decorators import admin_required, login_required
from campus.db.connection import get_db, now_str
from campus.services.acl import auto_join_default_group, user_group_ids_of
from campus.services.audit import add_log
from campus.services.users import (
    parse_user_profile_body,
    user_dict,
    user_dept_display,
    validate_registration_user_refs,
    lookup_employee_by_username,
)
from campus.settings import APP_CONFIG

bp = Blueprint("users", __name__)

VALID_ROLES = ("admin", "user")


def _user_row_dict(row):
    return user_dict(row)


def _user_with_groups(db, row):
    d = _user_row_dict(row)
    d["group_ids"] = user_group_ids_of(db, row["id"])
    d["dept_display"] = user_dept_display(row)
    return d


@bp.get("/api/users")
@admin_required
def api_users():
    """用户列表（仅系统管理员）。支持按分组、关键字过滤。"""
    db = get_db()
    group_id = request.args.get("group_id", type=int)
    q = (request.args.get("q") or "").strip().lower()
    sql = ("SELECT u.id, u.username, u.display_name, u.role, u.supervisor, u.department, "
           "u.dept_level2, u.dept_level3, u.job_roles FROM users u")
    params = []
    if group_id:
        sql += (" JOIN user_group_members m ON m.user_id=u.id AND m.group_id=?")
        params.append(group_id)
    sql += " ORDER BY u.id"
    rows = db.execute(sql, params).fetchall()
    out = [_user_with_groups(db, r) for r in rows]
    if q:
        out = [u for u in out if q in (u["username"] or "").lower()
               or q in (u["display_name"] or "").lower()
               or q in (u.get("dept_display") or "").lower()
               or q in (u.get("supervisor") or "").lower()]
    return jsonify(out)


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
@admin_required
def api_user_create():
    b = request.get_json(force=True)
    username = (b.get("username") or "").strip()
    if not username:
        return jsonify({"error": "用户名（工号）不能为空"}), 400
    password = b.get("password") or APP_CONFIG["security"]["default_password"]
    role = b.get("role", "user")
    if role not in VALID_ROLES:
        return jsonify({"error": "角色不合法"}), 400

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
             json.dumps([], ensure_ascii=False), now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "用户名已存在"}), 400
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    # 自动加入默认分组以获得基线权限
    auto_join_default_group(db, uid)
    add_log(g.user, "user", f"{g.user['display_name']} 创建了用户「{fields['display_name']}」")
    db.commit()
    return jsonify({"ok": True, "id": uid})


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
        "dept_level2=?, dept_level3=? WHERE id=?",
        (fields["display_name"], role, fields["supervisor"], fields["department"],
         fields["dept_level2"], fields["dept_level3"], uid),
    )
    if b.get("password"):
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(b["password"]), uid))
    add_log(g.user, "user", f"{g.user['display_name']} 更新了用户「{user['display_name']}」的信息")
    db.commit()
    return jsonify({"ok": True})


@bp.put("/api/users/batch")
@admin_required
def api_users_batch_update():
    """批量修改用户资料（主管/二层部门/三层部门/姓名）。"""
    b = request.get_json(force=True)
    ids = b.get("ids") or []
    if not ids:
        return jsonify({"error": "请选择至少一个用户"}), 400
    patch = b.get("patch") or {}
    allowed = {"display_name", "supervisor", "dept_level2", "dept_level3"}
    keys = [k for k in allowed if k in patch]
    if not keys:
        return jsonify({"error": "未提供可批量修改的字段"}), 400
    db = get_db()
    updated = 0
    for uid in ids:
        row = db.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
        if not row:
            continue
        body = {k: patch[k] for k in keys}
        # 用解析器校验（合并既有值）
        profile_body = {
            "display_name": body.get("display_name", row["display_name"]),
            "supervisor": body.get("supervisor", row["supervisor"]),
            "dept_level2": body.get("dept_level2", row["dept_level2"] if "dept_level2" in row.keys() else ""),
            "dept_level3": body.get("dept_level3", row["dept_level3"] if "dept_level3" in row.keys() else ""),
        }
        err, fields = parse_user_profile_body(profile_body)
        if err:
            continue
        db.execute(
            "UPDATE users SET display_name=?, supervisor=?, department=?, dept_level2=?, dept_level3=? WHERE id=?",
            (fields["display_name"], fields["supervisor"], fields["department"],
             fields["dept_level2"], fields["dept_level3"], int(uid)),
        )
        updated += 1
    add_log(g.user, "user", f"{g.user['display_name']} 批量修改了 {updated} 个用户资料")
    db.commit()
    return jsonify({"ok": True, "updated": updated})


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
