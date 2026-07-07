# -*- coding: utf-8 -*-
"""用户管理接口（纯模块授权模型，已取消业务角色与用户/资源分组）。

系统仅区分「系统管理员」(admin) 与普通用户 (user)。附属信息字段由
config/user_fields.json 配置；唯一性由工号(username)决定。
"""
import sqlite3

from flask import Blueprint, g, jsonify, request

from campus.core.roles_store import role_keys, role_label
from campus.core.settings import APP_CONFIG
from campus.db.connection import get_db
from campus.domain.employees import user_dept_display
from campus.services.audit import add_log
from campus.services.users import (
    apply_role_to_user,
    builtin_fields,
    custom_fields,
    lookup_employee_for_registration,
    normalize_job_roles_payload,
    parse_extra,
    parse_user_profile_body,
    persist_user_columns,
    search_employees_for_registration,
    user_dict,
    validate_registration_user_refs,
)
from campus.web.guards import admin_required, login_required

bp = Blueprint("users", __name__)


def _resolve_job_roles_update(body, role, user):
    """更新用户时：非面试官清空岗位；面试官按请求体或保留原值。"""
    if role != "interviewer":
        return []
    if "job_roles" in body:
        return normalize_job_roles_payload(body) or []
    from campus.domain.employees import parse_job_roles
    return parse_job_roles(user["job_roles"] if user else None)


def _user_row_dict(row):
    return user_dict(row)


def _user_full(db, row):
    d = _user_row_dict(row)
    d["dept_display"] = user_dept_display(row)
    return d


@bp.get("/api/users")
@admin_required
def api_users():
    """用户列表（仅系统管理员）。支持按关键字过滤（工号/姓名/主管/部门）。"""
    db = get_db()
    q = (request.args.get("q") or "").strip().lower()
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    out = [_user_full(db, r) for r in rows]
    if q:
        out = [u for u in out
               if q in (u["username"] or "").lower()
               or q in (u["display_name"] or "").lower()
               or q in (u.get("supervisor") or "").lower()
               or q in (u.get("dept_display") or "").lower()]
    return jsonify(out)


@bp.get("/api/users/suggest-employee")
@login_required
def api_suggest_employee():
    """登记页拓源人/接口人：按工号/姓名/部门/主管模糊匹配，返回得分最高的前 5 条。"""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": [], "too_many": False, "total": 0})
    result = search_employees_for_registration(get_db(), q, limit=5)
    return jsonify({
        "items": result["items"],
        "too_many": result["too_many"],
        "total": result["total"],
    })


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
    """按工号或姓名查询用户（登记页拓源人/接口人）。"""
    query = (request.args.get("q") or request.args.get("username") or "").strip()
    if not query:
        return jsonify({"error": "请输入工号或姓名"}), 400
    row = lookup_employee_for_registration(get_db(), query)
    if not row:
        return jsonify({
            "found": False,
            "error": f"「{query}」未匹配到系统用户，请从列表选择或联系管理员",
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
    username = (b.get("username") or b.get("employee_id") or "").strip()
    if not username:
        return jsonify({"error": "用户名（工号）不能为空"}), 400
    password = b.get("password") or APP_CONFIG["security"]["default_password"]
    role = (b.get("role") or "user").strip()
    if role not in role_keys():
        return jsonify({"error": f"角色不合法：{role}"}), 400

    err, fields = parse_user_profile_body(b)
    if err:
        return jsonify({"error": err}), 400

    db = get_db()
    job_roles = normalize_job_roles_payload(b)
    if "job_roles" not in b and role == "interviewer":
        from campus.core.roles_store import get_role
        rdef = get_role(role)
        job_roles = list((rdef or {}).get("interview_positions") or [])
    elif job_roles is None:
        job_roles = []
    try:
        persist_user_columns(db, None, fields, role, password=password,
                              is_create=True, username=username, job_roles=job_roles)
    except sqlite3.IntegrityError:
        return jsonify({"error": "工号已存在"}), 400
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    # 新建用户默认应用角色权限模板（除非显式关闭）
    if b.get("apply_role", True):
        apply_role_to_user(db, uid, role)
    add_log(g.user, "user", f"{g.user['display_name']} 创建了用户「{fields['builtin'].get('display_name')}」（角色：{role_label(role)}）")
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
    role = (b.get("role") or user["role"]).strip()
    if role not in role_keys():
        return jsonify({"error": f"角色不合法：{role}"}), 400

    # 合并既有值后再校验（前端可能只提交部分字段）
    merged = dict(b)
    for f in builtin_fields():
        key = f["key"]
        if key not in merged or merged.get(key) in (None, ""):
            merged[key] = user[key] if key in user.keys() else ""
    for f in custom_fields():
        key = f["key"]
        if key not in merged:
            merged[key] = parse_extra(user["extra"]).get(key, "")
    err, fields = parse_user_profile_body(merged)
    if err:
        return jsonify({"error": err}), 400

    persist_user_columns(db, uid, fields, role, password=b.get("password"),
                          job_roles=_resolve_job_roles_update(b, role, user))
    # 显式要求重新应用角色权限（覆盖该用户模块权限）
    if b.get("apply_role"):
        apply_role_to_user(db, uid, role)
    add_log(g.user, "user", f"{g.user['display_name']} 更新了用户「{user['display_name']}」的信息")
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/users/<int:uid>/apply-role")
@admin_required
def api_user_apply_role(uid):
    """将用户当前角色的权限模板应用到其 module_acl（覆盖原有模块权限）。"""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    cnt = apply_role_to_user(db, uid, user["role"])
    add_log(g.user, "permission",
            f"{g.user['display_name']} 对用户「{user['display_name']}」应用了角色「{role_label(user['role'])}」权限（{cnt} 项）")
    db.commit()
    return jsonify({"ok": True, "applied": cnt})


@bp.post("/api/users/apply-role-batch")
@admin_required
def api_users_apply_role_batch():
    """批量对所选用户应用其当前角色的权限模板。"""
    b = request.get_json(force=True)
    ids = b.get("ids") or []
    if not ids:
        return jsonify({"error": "请选择至少一个用户"}), 400
    db = get_db()
    total = 0
    for uid in ids:
        user = db.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
        if not user:
            continue
        total += apply_role_to_user(db, int(uid), user["role"])
    add_log(g.user, "permission",
            f"{g.user['display_name']} 批量应用角色权限到 {len(ids)} 个用户（共 {total} 项）")
    db.commit()
    return jsonify({"ok": True, "applied": total})


@bp.put("/api/users/batch")
@admin_required
def api_users_batch_update():
    """批量修改用户附属信息字段（任意 user_fields.json 中定义的字段）。"""
    b = request.get_json(force=True)
    ids = b.get("ids") or []
    if not ids:
        return jsonify({"error": "请选择至少一个用户"}), 400
    patch = b.get("patch") or {}
    cfg_keys = {f["key"] for f in builtin_fields()} | {f["key"] for f in custom_fields()}
    keys = [k for k in patch.keys() if k in cfg_keys]
    if not keys:
        return jsonify({"error": "未提供可批量修改的字段"}), 400
    db = get_db()
    updated = 0
    for uid in ids:
        row = db.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
        if not row:
            continue
        merged = {}
        for f in builtin_fields():
            k = f["key"]
            merged[k] = patch[k] if k in patch else (row[k] if k in row.keys() else "")
        existing_extra = parse_extra(row["extra"])
        for f in custom_fields():
            k = f["key"]
            merged[k] = patch[k] if k in patch else existing_extra.get(k, "")
        err, fields = parse_user_profile_body(merged)
        if err:
            continue
        persist_user_columns(db, int(uid), fields, row["role"])
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
    db.execute("DELETE FROM module_acl WHERE subject_type='user' AND subject_id=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    add_log(g.user, "user", f"{g.user['display_name']} 删除了用户「{user['display_name']}」")
    db.commit()
    return jsonify({"ok": True})
