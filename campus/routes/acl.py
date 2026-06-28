# -*- coding: utf-8 -*-
"""权限管理接口：用户分组 / 成员 / 分组模板 / 资源分组 / 权限模板 / ACL / 批量操作。

所有接口均需登录；管理类操作（创建/删除/授权）限系统管理员。批量授予 manage
权限需带 confirm=true 二次确认；批量操作支持 dry_run=true 仅返回影响预览。
权限变更一律写入操作日志（action='permission'）便于审计。
"""
import io
import json
import sqlite3

from flask import Blueprint, g, jsonify, request, send_file
from openpyxl import Workbook, load_workbook

from campus.auth.decorators import admin_required, login_required
from campus.db.connection import get_db, now_str
from campus.logging_util import log, who
from campus.services.acl import (
    RESOURCE_TYPE_GROUP,
    SUBJECT_TYPE_USER,
    SUBJECT_TYPE_USER_GROUP,
    accessible_resource_ids,
    acl_row_dict,
    descendant_user_group_ids,
    effective_permissions,
    module_acl_row_dict,
    module_entry,
    module_keys,
    module_readable_for,
    module_registry_payload,
    module_writable_for,
    permission_settings,
    user_group_ids_of,
)
from campus.services.audit import add_log

bp = Blueprint("acl", __name__)

PERM_FIELDS = ("perm_visibility", "perm_read", "perm_write", "perm_manage")


# ============================================================================
# 选项 / 配置下发
# ============================================================================

@bp.get("/api/permissions/options")
@login_required
def api_permission_options():
    db = get_db()
    users = [
        {"id": u["id"], "username": u["username"], "display_name": u["display_name"],
         "role": u["role"], "department": u["department"] or ""}
        for u in db.execute(
            "SELECT id, username, display_name, role, department FROM users ORDER BY id"
        ).fetchall()
    ]
    user_groups = [dict(r) for r in db.execute(
        "SELECT id, name, description, parent_id, created_at FROM user_groups ORDER BY id"
    ).fetchall()]
    members = [dict(r) for r in db.execute(
        "SELECT group_id, user_id FROM user_group_members"
    ).fetchall()]
    resource_groups = [dict(r) for r in db.execute(
        "SELECT id, name, description, parent_id, created_at FROM groups ORDER BY id"
    ).fetchall()]
    perm_templates = [dict(r) for r in db.execute(
        "SELECT id, name, description, perm_visibility, perm_read, perm_write, perm_manage, created_at "
        "FROM permission_templates ORDER BY id"
    ).fetchall()]
    ug_templates = [dict(r) for r in db.execute(
        "SELECT id, name, description, member_usernames, created_at FROM user_group_templates ORDER BY id"
    ).fetchall()]
    # 模块级 ACL：板块/模块注册表（恒门禁，无 enabled 开关）
    module_meta = []
    from campus.services.acl import MODULE_REGISTRY
    for entry in MODULE_REGISTRY:
        e = {"key": entry["key"], "label": entry["label"], "type": entry["type"]}
        if "items" in entry:
            e["items"] = [{"key": c["key"], "label": c["label"], "type": c["type"]}
                          for c in entry["items"]]
        module_meta.append(e)
    return jsonify({
        "settings": permission_settings(),
        "users": users,
        "user_groups": user_groups,
        "user_group_members": members,
        "user_group_templates": ug_templates,
        "resource_groups": resource_groups,
        "permission_templates": perm_templates,
        "resource_types": [{"value": RESOURCE_TYPE_GROUP, "label": "数据分组"}],
        "modules": module_meta,
    })


# ============================================================================
# 用户分组 CRUD
# ============================================================================

def _ug_dict(r):
    return {
        "id": r["id"], "name": r["name"], "description": r["description"] or "",
        "parent_id": r["parent_id"], "created_at": r["created_at"],
    }


@bp.get("/api/user-groups")
@login_required
def api_user_groups():
    db = get_db()
    rows = db.execute(
        "SELECT g.*, (SELECT COUNT(*) FROM user_group_members m WHERE m.group_id=g.id) AS member_count "
        "FROM user_groups g ORDER BY g.id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/user-groups")
@admin_required
def api_user_group_create():
    b = request.get_json(force=True)
    name = (b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "分组名不能为空"}), 400
    desc = (b.get("description") or "").strip()
    parent_id = b.get("parent_id")
    if parent_id is not None:
        parent_id = int(parent_id)
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO user_groups (name, description, parent_id, created_at) VALUES (?,?,?,?)",
            (name, desc, parent_id, now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "分组名已存在"}), 400
    add_log(g.user, "permission",
            f"{g.user['display_name']} 创建了用户分组「{name}」" + (f"（父分组#{parent_id}）" if parent_id else ""))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.put("/api/user-groups/<int:gid>")
@admin_required
def api_user_group_update(gid):
    b = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "用户分组不存在"}), 404
    name = (b.get("name") or row["name"]).strip()
    desc = (b.get("description", row["description"] or "")).strip()
    parent_id = b.get("parent_id", row["parent_id"])
    if parent_id is not None:
        parent_id = int(parent_id)
    if parent_id == gid:
        return jsonify({"error": "不能将自身设为父分组"}), 400
    # 防止环引用：父分组不能是自身的后代
    if parent_id is not None:
        cur = parent_id
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur == gid:
                return jsonify({"error": "不能将后代分组设为父分组（会形成环）"}), 400
            r = db.execute("SELECT parent_id FROM user_groups WHERE id=?", (cur,)).fetchone()
            cur = r["parent_id"] if r else None
    try:
        db.execute(
            "UPDATE user_groups SET name=?, description=?, parent_id=? WHERE id=?",
            (name, desc, parent_id, gid),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "分组名已存在"}), 400
    add_log(g.user, "permission", f"{g.user['display_name']} 编辑了用户分组「{name}」")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/user-groups/<int:gid>")
@admin_required
def api_user_group_delete(gid):
    db = get_db()
    row = db.execute("SELECT * FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "用户分组不存在"}), 404
    # 引用校验：子分组、ACL 条目
    child = db.execute("SELECT id FROM user_groups WHERE parent_id=?", (gid,)).fetchone()
    if child:
        return jsonify({"error": "该用户分组下仍有子分组，请先调整子分组的父分组"}), 400
    acl_cnt = db.execute(
        "SELECT COUNT(*) AS c FROM acl WHERE subject_type=? AND subject_id=?",
        (SUBJECT_TYPE_USER_GROUP, gid),
    ).fetchone()["c"]
    db.execute("DELETE FROM user_group_members WHERE group_id=?", (gid,))
    db.execute("DELETE FROM acl WHERE subject_type=? AND subject_id=?",
               (SUBJECT_TYPE_USER_GROUP, gid))
    db.execute("DELETE FROM user_groups WHERE id=?", (gid,))
    add_log(g.user, "permission",
            f"{g.user['display_name']} 删除了用户分组「{row['name']}」（解除 {acl_cnt} 条授权）")
    db.commit()
    return jsonify({"ok": True})


# ============================================================================
# 用户分组成员管理
# ============================================================================

@bp.get("/api/user-groups/<int:gid>/members")
@login_required
def api_user_group_members(gid):
    db = get_db()
    rows = db.execute(
        "SELECT u.id, u.username, u.display_name, u.role, u.supervisor, u.department, "
        "u.dept_level2, u.dept_level3 "
        "FROM user_group_members m JOIN users u ON u.id=m.user_id "
        "WHERE m.group_id=? ORDER BY u.id", (gid,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/user-groups/<int:gid>/members")
@admin_required
def api_user_group_members_add(gid):
    """单个/批量添加成员。

    支持三种方式（可组合）：
      - user_ids: [1,2,3]
      - usernames: ["hr01","hr02"]
      - filter: {dept_level2, supervisor, department} 按部门/主管筛选批量加入
    """
    db = get_db()
    row = db.execute("SELECT name FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "用户分组不存在"}), 404
    b = request.get_json(force=True)
    user_ids = list(b.get("user_ids") or [])
    usernames = b.get("usernames") or []
    flt = b.get("filter") or {}

    if usernames:
        ph = ",".join("?" * len(usernames))
        rows = db.execute(f"SELECT id FROM users WHERE username IN ({ph})", usernames).fetchall()
        user_ids = user_ids + [r["id"] for r in rows]
    if flt and (flt.get("dept_level2") or flt.get("supervisor") or flt.get("department")):
        sql = "SELECT id FROM users WHERE 1=1"
        args = []
        if flt.get("dept_level2"):
            sql += " AND dept_level2=?"
            args.append(flt["dept_level2"])
        if flt.get("supervisor"):
            sql += " AND supervisor=?"
            args.append(flt["supervisor"])
        if flt.get("department"):
            sql += " AND department=?"
            args.append(flt["department"])
        rows = db.execute(sql, args).fetchall()
        user_ids = user_ids + [r["id"] for r in rows]
    user_ids = [int(i) for i in user_ids if i is not None]
    added = 0
    for uid in user_ids:
        try:
            db.execute(
                "INSERT INTO user_group_members (group_id, user_id, created_at) VALUES (?,?,?)",
                (gid, uid, now_str()),
            )
            added += 1
        except sqlite3.IntegrityError:
            continue
    add_log(g.user, "permission",
            f"{g.user['display_name']} 向用户分组「{row['name']}」添加了 {added} 名成员")
    db.commit()
    return jsonify({"ok": True, "added": added})


@bp.delete("/api/user-groups/<int:gid>/members/<int:uid>")
@admin_required
def api_user_group_member_remove(gid, uid):
    db = get_db()
    row = db.execute("SELECT name FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "用户分组不存在"}), 404
    db.execute("DELETE FROM user_group_members WHERE group_id=? AND user_id=?", (gid, uid))
    add_log(g.user, "permission",
            f"{g.user['display_name']} 从用户分组「{row['name']}」移除了 1 名成员")
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/user-groups/<int:gid>/members/batch-remove")
@admin_required
def api_user_group_members_batch_remove(gid):
    """批量移除成员（如员工离职一键清退）。"""
    db = get_db()
    row = db.execute("SELECT name FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "用户分组不存在"}), 404
    ids = request.get_json(force=True).get("user_ids") or []
    if not ids:
        return jsonify({"error": "请选择要移除的成员"}), 400
    placeholders = ",".join("?" * len(ids))
    cur = db.execute(
        f"DELETE FROM user_group_members WHERE group_id=? AND user_id IN ({placeholders})",
        [gid, *ids],
    )
    add_log(g.user, "permission",
            f"{g.user['display_name']} 从用户分组「{row['name']}」批量移除了 {cur.rowcount} 名成员")
    db.commit()
    return jsonify({"ok": True, "removed": cur.rowcount})


# ============================================================================
# 用户分组模板
# ============================================================================

@bp.get("/api/user-group-templates")
@login_required
def api_ug_templates():
    rows = get_db().execute(
        "SELECT id, name, description, member_usernames, created_at FROM user_group_templates ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["member_usernames"] = json.loads(r["member_usernames"] or "[]")
        except (TypeError, json.JSONDecodeError):
            d["member_usernames"] = []
        out.append(d)
    return jsonify(out)


@bp.post("/api/user-group-templates")
@admin_required
def api_ug_template_save():
    b = request.get_json(force=True)
    name = (b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "模板名不能为空"}), 400
    desc = (b.get("description") or "").strip()
    usernames = b.get("member_usernames") or []
    if not isinstance(usernames, list):
        return jsonify({"error": "member_usernames 须为列表"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO user_group_templates (name, description, member_usernames, created_at) VALUES (?,?,?,?)",
        (name, desc, json.dumps(usernames, ensure_ascii=False), now_str()),
    )
    add_log(g.user, "permission",
            f"{g.user['display_name']} 保存了用户分组模板「{name}」（{len(usernames)} 名成员）")
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.post("/api/user-group-templates/<int:tid>/apply")
@admin_required
def api_ug_template_apply(tid):
    """套用模板：创建一个新用户分组并加入模板中的成员（工号未找到的跳过）。"""
    b = request.get_json(force=True) or {}
    new_name = (b.get("name") or "").strip()
    db = get_db()
    tpl = db.execute("SELECT * FROM user_group_templates WHERE id=?", (tid,)).fetchone()
    if not tpl:
        return jsonify({"error": "模板不存在"}), 404
    if not new_name:
        new_name = tpl["name"]
    try:
        cur = db.execute(
            "INSERT INTO user_groups (name, description, parent_id, created_at) VALUES (?,?,NULL,?)",
            (new_name, tpl["description"] or "", now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "分组名已存在，请指定新名称"}), 400
    new_gid = cur.lastrowid
    try:
        usernames = json.loads(tpl["member_usernames"] or "[]")
    except (TypeError, json.JSONDecodeError):
        usernames = []
    added = 0
    if usernames:
        ph = ",".join("?" * len(usernames))
        rows = db.execute(f"SELECT id, username FROM users WHERE username IN ({ph})", usernames).fetchall()
        found = {r["username"]: r["id"] for r in rows}
        for un in usernames:
            uid = found.get(un)
            if not uid:
                continue
            try:
                db.execute(
                    "INSERT INTO user_group_members (group_id, user_id, created_at) VALUES (?,?,?)",
                    (new_gid, uid, now_str()),
                )
                added += 1
            except sqlite3.IntegrityError:
                continue
    add_log(g.user, "permission",
            f"{g.user['display_name']} 套用模板「{tpl['name']}」创建了用户分组「{new_name}」（加入 {added} 人）")
    db.commit()
    return jsonify({"ok": True, "id": new_gid, "added": added, "skipped": len(usernames) - added})


@bp.delete("/api/user-group-templates/<int:tid>")
@admin_required
def api_ug_template_delete(tid):
    db = get_db()
    row = db.execute("SELECT name FROM user_group_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        return jsonify({"error": "模板不存在"}), 404
    db.execute("DELETE FROM user_group_templates WHERE id=?", (tid,))
    add_log(g.user, "permission", f"{g.user['display_name']} 删除了用户分组模板「{row['name']}」")
    db.commit()
    return jsonify({"ok": True})


# ============================================================================
# 资源分组（扩展原 groups）：增删改查 + 引用校验
# ============================================================================

@bp.get("/api/resource-groups")
@login_required
def api_resource_groups():
    rows = get_db().execute(
        "SELECT g.id, g.name, g.description, g.parent_id, g.created_at, "
        "(SELECT COUNT(*) FROM candidates c WHERE c.group_id=g.id) AS candidate_count, "
        "(SELECT COUNT(*) FROM groups gc WHERE gc.parent_id=g.id) AS child_count "
        "FROM groups g ORDER BY g.id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/resource-groups")
@admin_required
def api_resource_group_create():
    b = request.get_json(force=True)
    name = (b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "资源分组名不能为空"}), 400
    desc = (b.get("description") or "").strip()
    parent_id = b.get("parent_id")
    if parent_id is not None:
        parent_id = int(parent_id)
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO groups (name, description, parent_id, created_at) VALUES (?,?,?,?)",
            (name, desc, parent_id, now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "资源分组名已存在"}), 400
    add_log(g.user, "permission", f"{g.user['display_name']} 创建了资源分组「{name}」")
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.put("/api/resource-groups/<int:gid>")
@admin_required
def api_resource_group_update(gid):
    b = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "资源分组不存在"}), 404
    name = (b.get("name") or row["name"]).strip()
    desc = (b.get("description", row["description"] or "")).strip()
    parent_id = b.get("parent_id", row["parent_id"])
    if parent_id is not None:
        parent_id = int(parent_id)
    if parent_id == gid:
        return jsonify({"error": "不能将自身设为父分组"}), 400
    if parent_id is not None:
        cur = parent_id
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur == gid:
                return jsonify({"error": "不能将后代分组设为父分组（会形成环）"}), 400
            r = db.execute("SELECT parent_id FROM groups WHERE id=?", (cur,)).fetchone()
            cur = r["parent_id"] if r else None
    try:
        db.execute("UPDATE groups SET name=?, description=?, parent_id=? WHERE id=?",
                   (name, desc, parent_id, gid))
    except sqlite3.IntegrityError:
        return jsonify({"error": "资源分组名已存在"}), 400
    add_log(g.user, "permission", f"{g.user['display_name']} 编辑了资源分组「{name}」")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/resource-groups/<int:gid>")
@admin_required
def api_resource_group_delete(gid):
    db = get_db()
    row = db.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "资源分组不存在"}), 404
    cand_cnt = db.execute("SELECT COUNT(*) AS c FROM candidates WHERE group_id=?", (gid,)).fetchone()["c"]
    if cand_cnt > 0:
        return jsonify({"error": f"该资源分组下仍有 {cand_cnt} 名候选人，请先迁移后再删除"}), 400
    child = db.execute("SELECT id FROM groups WHERE parent_id=?", (gid,)).fetchone()
    if child:
        return jsonify({"error": "该资源分组下仍有子分组，请先调整子分组的父分组"}), 400
    acl_cnt = db.execute(
        "SELECT COUNT(*) AS c FROM acl WHERE resource_type=? AND resource_id=?",
        (RESOURCE_TYPE_GROUP, gid),
    ).fetchone()["c"]
    db.execute("DELETE FROM acl WHERE resource_type=? AND resource_id=?", (RESOURCE_TYPE_GROUP, gid))
    # 解除仍指向该分组的外键引用（用户、面试可用时段的 group_id；interview_bookings 无 group_id 列）
    db.execute("UPDATE users SET group_id=NULL WHERE group_id=?", (gid,))
    db.execute("UPDATE interviewer_availability SET group_id=NULL WHERE group_id=?", (gid,))
    # 候选人回退到未分组（理论上 cand_cnt==0 时不会触发，防御性处理）
    db.execute("UPDATE candidates SET group_id=NULL WHERE group_id=?", (gid,))
    db.execute("DELETE FROM groups WHERE id=?", (gid,))
    add_log(g.user, "permission",
            f"{g.user['display_name']} 删除了资源分组「{row['name']}」（清除 {acl_cnt} 条授权）")
    db.commit()
    return jsonify({"ok": True})


# ============================================================================
# 权限模板
# ============================================================================

@bp.post("/api/permission-templates")
@admin_required
def api_perm_template_create():
    b = request.get_json(force=True)
    name = (b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "模板名不能为空"}), 400
    perms = _coerce_perms(b)
    db = get_db()
    cur = db.execute(
        "INSERT INTO permission_templates (name, description, perm_visibility, perm_read, perm_write, perm_manage, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, (b.get("description") or "").strip(), perms["perm_visibility"], perms["perm_read"],
         perms["perm_write"], perms["perm_manage"], now_str()),
    )
    add_log(g.user, "permission", f"{g.user['display_name']} 创建了权限模板「{name}」")
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.put("/api/permission-templates/<int:tid>")
@admin_required
def api_perm_template_update(tid):
    b = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM permission_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        return jsonify({"error": "权限模板不存在"}), 404
    name = (b.get("name") or row["name"]).strip()
    desc = b.get("description", row["description"] or "")
    perms = _coerce_perms({**dict(row), **b})
    db.execute(
        "UPDATE permission_templates SET name=?, description=?, perm_visibility=?, perm_read=?, perm_write=?, perm_manage=? WHERE id=?",
        (name, desc, perms["perm_visibility"], perms["perm_read"], perms["perm_write"], perms["perm_manage"], tid),
    )
    add_log(g.user, "permission", f"{g.user['display_name']} 更新了权限模板「{name}」")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/permission-templates/<int:tid>")
@admin_required
def api_perm_template_delete(tid):
    db = get_db()
    row = db.execute("SELECT name FROM permission_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        return jsonify({"error": "权限模板不存在"}), 404
    db.execute("DELETE FROM permission_templates WHERE id=?", (tid,))
    add_log(g.user, "permission", f"{g.user['display_name']} 删除了权限模板「{row['name']}」")
    db.commit()
    return jsonify({"ok": True})


# ============================================================================
# ACL 单条 / 查询
# ============================================================================

def _coerce_perms(d):
    out = {}
    for k in PERM_FIELDS:
        v = d.get(k)
        out[k] = 1 if _truthy(v) else 0
    return out


def _truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() in ("1", "true", "True", "yes", "on")
    return False


@bp.get("/api/acl")
@login_required
def api_acl_query():
    """按 resource 查询（默认）或按 subject 查询。"""
    db = get_db()
    resource_type = request.args.get("resource_type")
    resource_id = request.args.get("resource_id", type=int)
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id", type=int)
    sql = "SELECT * FROM acl WHERE 1=1"
    args = []
    if resource_type:
        sql += " AND resource_type=?"
        args.append(resource_type)
        if resource_id is not None:
            sql += " AND resource_id=?"
            args.append(resource_id)
    if subject_type:
        sql += " AND subject_type=?"
        args.append(subject_type)
        if subject_id is not None:
            sql += " AND subject_id=?"
            args.append(subject_id)
    sql += " ORDER BY id"
    rows = db.execute(sql, args).fetchall()
    return jsonify([acl_row_dict(r) for r in rows])


@bp.put("/api/acl")
@admin_required
def api_acl_upsert():
    """单条 upsert：subject × resource 的四项权限。"""
    b = request.get_json(force=True)
    err = _validate_acl_subject_resource(b)
    if err:
        return jsonify({"error": err}), 400
    perms = _coerce_perms(b)
    db = get_db()
    _upsert_acl(db, b["subject_type"], int(b["subject_id"]), b["resource_type"], int(b["resource_id"]), perms)
    _log_acl_change(g.user, b, perms, action="upsert")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/acl")
@admin_required
def api_acl_delete():
    b = request.get_json(force=True)
    err = _validate_acl_subject_resource(b)
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    db.execute(
        "DELETE FROM acl WHERE subject_type=? AND subject_id=? AND resource_type=? AND resource_id=?",
        (b["subject_type"], int(b["subject_id"]), b["resource_type"], int(b["resource_id"])),
    )
    _log_acl_change(g.user, b, None, action="revoke")
    db.commit()
    return jsonify({"ok": True})


def _validate_acl_subject_resource(b):
    if b.get("subject_type") not in (SUBJECT_TYPE_USER, SUBJECT_TYPE_USER_GROUP):
        return "subject_type 不合法"
    if b.get("resource_type") != RESOURCE_TYPE_GROUP:
        return "resource_type 不合法"
    if b.get("subject_id") is None:
        return "subject_id 不能为空"
    if b.get("resource_id") is None:
        return "resource_id 不能为空"
    return None


def _upsert_acl(db, s_type, s_id, r_type, r_id, perms):
    existing = db.execute(
        "SELECT id FROM acl WHERE subject_type=? AND subject_id=? AND resource_type=? AND resource_id=?",
        (s_type, s_id, r_type, r_id),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE acl SET perm_visibility=?, perm_read=?, perm_write=?, perm_manage=? WHERE id=?",
            (perms["perm_visibility"], perms["perm_read"], perms["perm_write"], perms["perm_manage"], existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO acl (subject_type, subject_id, resource_type, resource_id, "
            "perm_visibility, perm_read, perm_write, perm_manage, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (s_type, s_id, r_type, r_id, perms["perm_visibility"], perms["perm_read"],
             perms["perm_write"], perms["perm_manage"], now_str()),
        )


def _log_acl_change(user, b, perms, action):
    s_label = f"用户#{b.get('subject_id')}" if b.get("subject_type") == SUBJECT_TYPE_USER else f"用户分组#{b.get('subject_id')}"
    r_label = f"{b.get('resource_type')}#{b.get('resource_id')}"
    if perms is None:
        msg = f"{user['display_name']} 撤销了 {s_label} 对 {r_label} 的全部权限"
    else:
        flags = [k.replace("perm_", "") for k in PERM_FIELDS if perms[k]]
        msg = f"{user['display_name']} 设置 {s_label} 对 {r_label} 的权限：{('、'.join(flags)) or '无'}"
    add_log(user, "permission", msg)


# ============================================================================
# 批量操作：授权 / 撤权 / 复制 / 导入 / 导出 / 预览
# ============================================================================

@bp.post("/api/acl/batch")
@admin_required
def api_acl_batch():
    """批量授权/撤权。

    body:
      entries: [{subject_type, subject_id, resource_type, resource_id,
                 perm_visibility, perm_read, perm_write, perm_manage}]
      mode: "set" | "revoke"   (默认 set)
      dry_run: true 仅返回影响预览
      confirm: true 才允许授予 manage 权限（二次验证）
    """
    b = request.get_json(force=True)
    entries = b.get("entries") or []
    if not entries:
        return jsonify({"error": "entries 不能为空"}), 400
    mode = b.get("mode", "set")
    dry_run = bool(b.get("dry_run"))
    confirm = bool(b.get("confirm"))

    # 校验
    for e in entries:
        err = _validate_acl_subject_resource(e)
        if err:
            return jsonify({"error": err}), 400
    if mode == "set" and not dry_run:
        for e in entries:
            perms = _coerce_perms(e)
            if perms["perm_manage"] and not confirm:
                return jsonify({
                    "error": "批量授予管理权限需二次确认，请勾选 confirm=true 后重试",
                    "code": "manage_requires_confirm",
                }), 400

    # 影响预览
    subjects = {(e["subject_type"], e["subject_id"]) for e in entries}
    resources = {(e["resource_type"], e["resource_id"]) for e in entries}
    preview = {
        "subject_count": len(subjects),
        "resource_count": len(resources),
        "entry_count": len(entries),
        "subjects": [{"type": s[0], "id": s[1]} for s in sorted(subjects)],
        "resources": [{"type": r[0], "id": r[1]} for r in sorted(resources)],
    }
    if dry_run:
        preview["mode"] = mode
        return jsonify({"ok": True, "dry_run": True, "preview": preview})

    db = get_db()
    affected = 0
    for e in entries:
        if mode == "revoke":
            db.execute(
                "DELETE FROM acl WHERE subject_type=? AND subject_id=? AND resource_type=? AND resource_id=?",
                (e["subject_type"], int(e["subject_id"]), e["resource_type"], int(e["resource_id"])),
            )
            affected += 1
        else:
            perms = _coerce_perms(e)
            _upsert_acl(db, e["subject_type"], int(e["subject_id"]), e["resource_type"], int(e["resource_id"]), perms)
            affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 批量{('撤销' if mode == 'revoke' else '设置')}了 {affected} 条权限"
            f"（影响 {len(subjects)} 个主体、{len(resources)} 个资源）")
    db.commit()
    return jsonify({"ok": True, "affected": affected, "preview": preview})


@bp.post("/api/acl/copy")
@admin_required
def api_acl_copy():
    """跨资源复制权限：从 source_resource 复制全部 ACL 到 target_resources。

    body: {resource_type, source_resource_id, target_resource_ids:[...], dry_run, confirm}
    """
    b = request.get_json(force=True)
    r_type = b.get("resource_type", RESOURCE_TYPE_GROUP)
    src = b.get("source_resource_id")
    targets = b.get("target_resource_ids") or []
    if src is None:
        return jsonify({"error": "source_resource_id 不能为空"}), 400
    if not targets:
        return jsonify({"error": "target_resource_ids 不能为空"}), 400
    dry_run = bool(b.get("dry_run"))
    confirm = bool(b.get("confirm"))

    db = get_db()
    src_rows = db.execute(
        "SELECT * FROM acl WHERE resource_type=? AND resource_id=?",
        (r_type, int(src)),
    ).fetchall()
    has_manage = any(int(r["perm_manage"]) for r in src_rows)
    preview = {
        "source_resource_id": int(src),
        "target_resource_ids": [int(t) for t in targets],
        "acl_rows": len(src_rows),
        "has_manage": has_manage,
    }
    if has_manage and not confirm and not dry_run:
        return jsonify({
            "error": "源资源包含管理权限，复制需二次确认（confirm=true）",
            "code": "manage_requires_confirm",
            "preview": preview,
        }), 400
    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "preview": preview})

    affected = 0
    for t in targets:
        for r in src_rows:
            perms = {f"perm_{k}": int(r[f"perm_{k}"]) for k in ("visibility", "read", "write", "manage")}
            _upsert_acl(db, r["subject_type"], r["subject_id"], r_type, int(t), perms)
            affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 将资源#{src} 的权限复制到 {len(targets)} 个目标资源（共 {affected} 条）")
    db.commit()
    return jsonify({"ok": True, "affected": affected, "preview": preview})


@bp.get("/api/acl/export")
@admin_required
def api_acl_export():
    """导出当前权限矩阵为 Excel。"""
    db = get_db()
    users = {u["id"]: dict(u) for u in db.execute(
        "SELECT id, username, display_name FROM users").fetchall()}
    ugs = {g_["id"]: dict(g_) for g_ in db.execute(
        "SELECT id, name FROM user_groups").fetchall()}
    rgs = {r["id"]: dict(r) for r in db.execute(
        "SELECT id, name FROM groups").fetchall()}
    rows = db.execute("SELECT * FROM acl ORDER BY resource_type, resource_id, subject_type, subject_id").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "权限矩阵"
    headers = ["主体类型", "主体ID", "主体名称", "资源类型", "资源ID", "资源名称",
               "可见性", "读", "写", "管理"]
    ws.append(headers)
    for r in rows:
        if r["subject_type"] == SUBJECT_TYPE_USER:
            s_name = users.get(r["subject_id"], {}).get("display_name", "")
        else:
            s_name = ugs.get(r["subject_id"], {}).get("name", "")
        r_name = rgs.get(r["resource_id"], {}).get("name", "")
        ws.append([
            "用户" if r["subject_type"] == SUBJECT_TYPE_USER else "用户分组",
            r["subject_id"], s_name,
            r["resource_type"], r["resource_id"], r_name,
            r["perm_visibility"], r["perm_read"], r["perm_write"], r["perm_manage"],
        ])
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, len(h) * 2 + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    add_log(g.user, "export", f"{g.user['display_name']} 导出了权限矩阵（{len(rows)} 条）")
    db.commit()
    resp = send_file(buf, as_attachment=True, download_name="权限矩阵.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["X-Export-Count"] = str(len(rows))
    return resp


@bp.post("/api/acl/import")
@admin_required
def api_acl_import():
    """通过 Excel 批量导入权限矩阵（表头同 export）。"""
    if "file" not in request.files:
        return jsonify({"error": "请选择 Excel 文件"}), 400
    try:
        wb = load_workbook(request.files["file"], data_only=True)
    except Exception:
        return jsonify({"error": "文件解析失败，请上传 .xlsx 格式文件"}), 400
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return jsonify({"error": "Excel 内容为空"}), 400
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    col = {h: i for i, h in enumerate(header)}

    def idx(name, aliases=()):
        for n in (name,) + aliases:
            if n in col:
                return col[n]
        return None

    i_st = idx("主体类型")
    i_sid = idx("主体ID")
    i_rt = idx("资源类型")
    i_rid = idx("资源ID")
    i_v = idx("可见性")
    i_r = idx("读")
    i_w = idx("写")
    i_m = idx("管理")
    if None in (i_st, i_sid, i_rt, i_rid):
        return jsonify({"error": "表头缺少必要列（主体类型/主体ID/资源类型/资源ID）"}), 400

    db = get_db()
    # 预检 manage 二次确认
    confirm = (request.form.get("confirm") in ("1", "true", "True")) or \
              (request.args.get("confirm") in ("1", "true", "True"))
    dry_run = (request.form.get("dry_run") in ("1", "true", "True"))

    parsed = []
    for raw in rows[1:]:
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        s_type_label = str(raw[i_st] or "").strip()
        s_type = SUBJECT_TYPE_USER if s_type_label in ("用户", "user") else SUBJECT_TYPE_USER_GROUP
        try:
            s_id = int(raw[i_sid])
            r_id = int(raw[i_rid])
        except (TypeError, ValueError):
            continue
        r_type = str(raw[i_rt] or "").strip() or RESOURCE_TYPE_GROUP

        def flag(v):
            return 1 if str(v or "").strip() in ("1", "true", "True", "yes") else 0
        perms = {
            "perm_visibility": flag(raw[i_v] if i_v is not None else 0),
            "perm_read": flag(raw[i_r] if i_r is not None else 0),
            "perm_write": flag(raw[i_w] if i_w is not None else 0),
            "perm_manage": flag(raw[i_m] if i_m is not None else 0),
        }
        parsed.append({"subject_type": s_type, "subject_id": s_id,
                       "resource_type": r_type, "resource_id": r_id, **perms})

    has_manage = any(p["perm_manage"] for p in parsed)
    preview = {"entry_count": len(parsed), "has_manage": has_manage}
    if has_manage and not confirm and not dry_run:
        return jsonify({"error": "导入包含管理权限，需二次确认（表单 confirm=1）",
                        "code": "manage_requires_confirm", "preview": preview}), 400
    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "preview": preview})

    affected = 0
    for p in parsed:
        _upsert_acl(db, p["subject_type"], p["subject_id"], p["resource_type"], p["resource_id"], p)
        affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 通过 Excel 导入了 {affected} 条权限")
    db.commit()
    return jsonify({"ok": True, "affected": affected, "preview": preview})


# ============================================================================
# 调试 / 自查：当前用户对某资源的有效权限
# ============================================================================

@bp.get("/api/acl/effective")
@login_required
def api_acl_effective():
    resource_type = request.args.get("resource_type", RESOURCE_TYPE_GROUP)
    resource_id = request.args.get("resource_id", type=int)
    if resource_id is None:
        return jsonify({"error": "resource_id 不能为空"}), 400
    perms = effective_permissions(get_db(), g.user, resource_type, resource_id)
    return jsonify({"resource_type": resource_type, "resource_id": resource_id,
                    "effective": perms, "settings": permission_settings()})


# 兼容引用：供 candidates 路由导入使用
def _accessible_resource_ids(db, user, resource_type=RESOURCE_TYPE_GROUP, perm="visibility"):
    return accessible_resource_ids(db, user, resource_type, perm)


# ============================================================================
# 模块级 ACL：板块/模块的可见性 / 可读性 / 可写性 / 管理
# ============================================================================

@bp.get("/api/permissions/modules")
@login_required
def api_permission_modules():
    """模块注册表 + 当前用户对各模块的有效权限（供前端导航渲染与切换拦截）。"""
    return jsonify({"modules": module_registry_payload(g.user)})


@bp.get("/api/module-acl")
@admin_required
def api_module_acl_query():
    """查询指定模块的全部 ACL 条目（矩阵数据）。"""
    module_key = (request.args.get("module_key") or "").strip()
    if not module_key or module_key not in module_keys():
        return jsonify({"error": "module_key 不合法"}), 400
    rows = get_db().execute(
        "SELECT * FROM module_acl WHERE module_key=? ORDER BY subject_type, subject_id",
        (module_key,),
    ).fetchall()
    return jsonify([module_acl_row_dict(r) for r in rows])


def _validate_module_acl_body(b):
    if b.get("subject_type") not in (SUBJECT_TYPE_USER, SUBJECT_TYPE_USER_GROUP):
        return "subject_type 不合法"
    if b.get("subject_id") is None:
        return "subject_id 不能为空"
    if not b.get("module_key") or b.get("module_key") not in module_keys():
        return "module_key 不合法"
    return None


def _module_perms_from_body(b):
    return {k: 1 if _truthy(b.get(k)) else 0 for k in PERM_FIELDS}


def _module_acl_upsert(db, s_type, s_id, module_key, perms):
    existing = db.execute(
        "SELECT id FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
        (s_type, s_id, module_key),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE module_acl SET perm_visibility=?, perm_read=?, perm_write=?, perm_manage=? WHERE id=?",
            (perms["perm_visibility"], perms["perm_read"], perms["perm_write"], perms["perm_manage"], existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO module_acl (subject_type, subject_id, module_key, "
            "perm_visibility, perm_read, perm_write, perm_manage, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (s_type, s_id, module_key, perms["perm_visibility"], perms["perm_read"],
             perms["perm_write"], perms["perm_manage"], now_str()),
        )


def _log_module_acl_change(user, b, perms, action):
    s_label = f"用户#{b.get('subject_id')}" if b.get("subject_type") == SUBJECT_TYPE_USER else f"用户分组#{b.get('subject_id')}"
    if perms is None:
        msg = f"{user['display_name']} 撤销了 {s_label} 对模块「{b.get('module_key')}」的全部权限"
    else:
        flags = [k.replace("perm_", "") for k in PERM_FIELDS if perms[k]]
        msg = f"{user['display_name']} 设置 {s_label} 对模块「{b.get('module_key')}」的权限：{('、'.join(flags)) or '无'}"
    add_log(user, "permission", msg)


@bp.put("/api/module-acl")
@admin_required
def api_module_acl_upsert():
    b = request.get_json(force=True)
    err = _validate_module_acl_body(b)
    if err:
        return jsonify({"error": err}), 400
    perms = _module_perms_from_body(b)
    db = get_db()
    _module_acl_upsert(db, b["subject_type"], int(b["subject_id"]), b["module_key"], perms)
    _log_module_acl_change(g.user, b, perms, action="upsert")
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/module-acl")
@admin_required
def api_module_acl_delete():
    b = request.get_json(force=True)
    err = _validate_module_acl_body(b)
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    db.execute(
        "DELETE FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
        (b["subject_type"], int(b["subject_id"]), b["module_key"]),
    )
    _log_module_acl_change(g.user, b, None, action="revoke")
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/user-groups/<int:gid>/members-info")
@admin_required
def api_user_group_members_info(gid):
    """查看指定分组下所有成员的完整信息（工号/姓名/主管/部门），支持搜索与多选过滤。

    查询参数：
      q: 关键字（匹配工号/姓名/主管/部门）
      ids: 逗号分隔的用户 id，仅返回这些用户（多选搜索）
    """
    db = get_db()
    ug = db.execute("SELECT id FROM user_groups WHERE id=?", (gid,)).fetchone()
    if not ug:
        return jsonify({"error": "分组不存在"}), 404
    sql = ("SELECT u.id, u.username, u.display_name, u.role, u.supervisor, u.department, "
           "u.dept_level2, u.dept_level3 FROM users u "
           "JOIN user_group_members m ON m.user_id=u.id WHERE m.group_id=? ORDER BY u.id")
    rows = db.execute(sql, (gid,)).fetchall()
    q = (request.args.get("q") or "").strip().lower()
    sel_ids = request.args.get("ids")
    out = []
    for r in rows:
        d = dict(r)
        d["dept_display"] = (r["department"] or "").strip()
        if q and not (q in (r["username"] or "").lower()
                      or q in (r["display_name"] or "").lower()
                      or q in (r["supervisor"] or "").lower()
                      or q in (r["department"] or "").lower()):
            continue
        out.append(d)
    if sel_ids:
        idset = {int(x) for x in sel_ids.split(",") if x.strip().isdigit()}
        out = [d for d in out if d["id"] in idset]
    return jsonify(out)


@bp.post("/api/module-acl/apply-to-subgroups")
@admin_required
def api_module_acl_apply_to_subgroups():
    """将一组模块权限批量应用到一个分组及其全部子分组。

    body: {group_id, module_keys:[...], perms:{perm_visibility,perm_read,perm_write,perm_manage}, confirm}
    """
    b = request.get_json(force=True)
    gid = int(b.get("group_id") or 0)
    if not gid:
        return jsonify({"error": "group_id 不能为空"}), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM user_groups WHERE id=?", (gid,)).fetchone():
        return jsonify({"error": "分组不存在"}), 404
    mks = b.get("module_keys") or []
    for mk in mks:
        if mk not in module_keys():
            return jsonify({"error": f"module_key 不合法: {mk}"}), 400
    perms = {k: 1 if _truthy(b.get(k)) else 0 for k in PERM_FIELDS}
    if perms["perm_manage"] and not b.get("confirm"):
        return jsonify({"error": "批量授予管理权限需二次确认（confirm=true）",
                        "code": "manage_requires_confirm"}), 400
    target_ids = descendant_user_group_ids(db, gid)
    affected = 0
    for tid in target_ids:
        for mk in mks:
            _module_acl_upsert(db, SUBJECT_TYPE_USER_GROUP, tid, mk, perms)
            affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 将模块权限批量应用到分组#{gid}及其 {len(target_ids)} 个子分组"
            f"（{len(mks)} 个模块，{affected} 条）")
    db.commit()
    return jsonify({"ok": True, "affected": affected,
                    "target_groups": target_ids, "group_count": len(target_ids)})


@bp.post("/api/module-acl/batch")
@admin_required
def api_module_acl_batch():
    """批量设置/撤销模块权限。支持 dry_run 预览与 manage 二次确认。"""
    b = request.get_json(force=True)
    entries = b.get("entries") or []
    if not entries:
        return jsonify({"error": "entries 不能为空"}), 400
    mode = b.get("mode", "set")
    dry_run = bool(b.get("dry_run"))
    confirm = bool(b.get("confirm"))
    for e in entries:
        err = _validate_module_acl_body(e)
        if err:
            return jsonify({"error": err}), 400
    if mode == "set" and not dry_run:
        for e in entries:
            if _module_perms_from_body(e)["perm_manage"] and not confirm:
                return jsonify({"error": "批量授予模块管理权限需二次确认（confirm=true）",
                                "code": "manage_requires_confirm"}), 400

    subjects = {(e["subject_type"], e["subject_id"]) for e in entries}
    modules = {e["module_key"] for e in entries}
    preview = {
        "subject_count": len(subjects),
        "module_count": len(modules),
        "entry_count": len(entries),
        "subjects": [{"type": s[0], "id": s[1]} for s in sorted(subjects)],
        "modules": sorted(modules),
    }
    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "preview": preview})

    db = get_db()
    affected = 0
    for e in entries:
        if mode == "revoke":
            db.execute(
                "DELETE FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
                (e["subject_type"], int(e["subject_id"]), e["module_key"]),
            )
            affected += 1
        else:
            perms = _module_perms_from_body(e)
            _module_acl_upsert(db, e["subject_type"], int(e["subject_id"]), e["module_key"], perms)
            affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 批量{('撤销' if mode == 'revoke' else '设置')}了 {affected} 条模块权限"
            f"（影响 {len(subjects)} 个主体、{len(modules)} 个模块）")
    db.commit()
    return jsonify({"ok": True, "affected": affected, "preview": preview})


@bp.get("/api/module-acl/export")
@admin_required
def api_module_acl_export():
    """导出模块权限矩阵为 Excel。"""
    db = get_db()
    users = {u["id"]: dict(u) for u in db.execute(
        "SELECT id, username, display_name FROM users").fetchall()}
    ugs = {g_["id"]: dict(g_) for g_ in db.execute(
        "SELECT id, name FROM user_groups").fetchall()}
    rows = db.execute("SELECT * FROM module_acl ORDER BY module_key, subject_type, subject_id").fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "模块权限矩阵"
    headers = ["模块", "主体类型", "主体ID", "主体名称", "可见性", "读", "写", "管理"]
    ws.append(headers)
    for r in rows:
        if r["subject_type"] == SUBJECT_TYPE_USER:
            s_name = users.get(r["subject_id"], {}).get("display_name", "")
        else:
            s_name = ugs.get(r["subject_id"], {}).get("name", "")
        ws.append([r["module_key"],
                   "用户" if r["subject_type"] == SUBJECT_TYPE_USER else "用户分组",
                   r["subject_id"], s_name,
                   r["perm_visibility"], r["perm_read"], r["perm_write"], r["perm_manage"]])
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, len(h) * 2 + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    add_log(g.user, "export", f"{g.user['display_name']} 导出了模块权限矩阵（{len(rows)} 条）")
    db.commit()
    resp = send_file(buf, as_attachment=True, download_name="模块权限矩阵.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["X-Export-Count"] = str(len(rows))
    return resp
