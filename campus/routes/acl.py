# -*- coding: utf-8 -*-
"""权限管理接口（扁平模块授权模型）。

权限模型：用户(工号) × 模块 的 visibility/read/write/manage 四勾选；
候选人数据为单一共享池，无用户分组/资源分组/模板/资源ACL。
所有接口均需登录；授权类操作限系统管理员。批量授予 manage 需 confirm=true。
权限变更一律写入操作日志（action='permission'）便于审计。
"""
import io

from flask import Blueprint, g, jsonify, request, send_file
from openpyxl import Workbook

from campus.auth.decorators import admin_required, login_required
from campus.db.connection import get_db, now_str
from campus.services.acl import (
    MODULE_REGISTRY,
    SUBJECT_TYPE_USER,
    module_acl_row_dict,
    module_keys,
    module_registry_payload,
    permission_settings,
)
from campus.services.audit import add_log
from campus.services.roles import roles_payload
from campus.services.users import user_dict, user_fields_config

bp = Blueprint("acl", __name__)

PERM_FIELDS = ("perm_visibility", "perm_read", "perm_write", "perm_manage")


# ============================================================================
# 选项 / 配置下发
# ============================================================================

@bp.get("/api/permissions/options")
@login_required
def api_permission_options():
    db = get_db()
    users = [user_dict(u) for u in db.execute("SELECT * FROM users ORDER BY id").fetchall()]
    module_meta = []
    for entry in MODULE_REGISTRY:
        e = {"key": entry["key"], "label": entry["label"], "type": entry["type"]}
        if "items" in entry:
            e["items"] = [{"key": c["key"], "label": c["label"], "type": c["type"]}
                          for c in entry["items"]]
        module_meta.append(e)
    return jsonify({
        "settings": permission_settings(),
        "users": users,
        "user_fields": user_fields_config(),
        "modules": module_meta,
        "roles": roles_payload(),
    })


# ============================================================================
# 模块级 ACL：用户(工号) × 模块 的 visibility/read/write/manage
# ============================================================================

@bp.get("/api/permissions/modules")
@login_required
def api_permission_modules():
    """模块注册表 + 当前用户对各模块的有效权限（供前端导航渲染与切换拦截）。"""
    return jsonify({"modules": module_registry_payload(g.user)})


@bp.get("/api/module-acl")
@admin_required
def api_module_acl_query():
    """查询全部模块 ACL 条目（可按 module_key / subject_id 过滤，矩阵数据）。"""
    db = get_db()
    sql = "SELECT * FROM module_acl WHERE subject_type=?"
    args = [SUBJECT_TYPE_USER]
    mk = (request.args.get("module_key") or "").strip()
    sid = request.args.get("subject_id", type=int)
    if mk:
        sql += " AND module_key=?"
        args.append(mk)
    if sid is not None:
        sql += " AND subject_id=?"
        args.append(sid)
    sql += " ORDER BY module_key, subject_id"
    rows = db.execute(sql, args).fetchall()
    return jsonify([module_acl_row_dict(r) for r in rows])


def _truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() in ("1", "true", "True", "yes", "on")
    return False


def _validate_module_acl_body(b):
    if b.get("subject_type") != SUBJECT_TYPE_USER:
        return "subject_type 不合法（仅支持用户）"
    if b.get("subject_id") is None:
        return "subject_id 不能为空"
    if not b.get("module_key") or b.get("module_key") not in module_keys():
        return "module_key 不合法"
    return None


def _module_perms_from_body(b):
    return {k: 1 if _truthy(b.get(k)) else 0 for k in PERM_FIELDS}


def _module_acl_upsert(db, s_id, module_key, perms):
    existing = db.execute(
        "SELECT id FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
        (SUBJECT_TYPE_USER, s_id, module_key),
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
            (SUBJECT_TYPE_USER, s_id, module_key, perms["perm_visibility"], perms["perm_read"],
             perms["perm_write"], perms["perm_manage"], now_str()),
        )


def _log_module_acl_change(user, b, perms, action):
    s_label = f"用户#{b.get('subject_id')}"
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
    _module_acl_upsert(db, int(b["subject_id"]), b["module_key"], perms)
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
        (SUBJECT_TYPE_USER, int(b["subject_id"]), b["module_key"]),
    )
    _log_module_acl_change(g.user, b, None, action="revoke")
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/module-acl/batch")
@admin_required
def api_module_acl_batch():
    """批量设置/撤销模块权限（Excel 式网格批量填充）。支持 dry_run 预览与 manage 二次确认。

    body:
      entries: [{subject_type:'user', subject_id, module_key,
                 perm_visibility, perm_read, perm_write, perm_manage}]
      mode: "set" | "revoke"
      dry_run, confirm
    """
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

    subjects = {int(e["subject_id"]) for e in entries}
    modules = {e["module_key"] for e in entries}
    preview = {
        "subject_count": len(subjects),
        "module_count": len(modules),
        "entry_count": len(entries),
        "subjects": sorted(subjects),
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
                (SUBJECT_TYPE_USER, int(e["subject_id"]), e["module_key"]),
            )
            affected += 1
        else:
            perms = _module_perms_from_body(e)
            _module_acl_upsert(db, int(e["subject_id"]), e["module_key"], perms)
            affected += 1
    add_log(g.user, "permission",
            f"{g.user['display_name']} 批量{('撤销' if mode == 'revoke' else '设置')}了 {affected} 条模块权限"
            f"（影响 {len(subjects)} 个用户、{len(modules)} 个模块）")
    db.commit()
    return jsonify({"ok": True, "affected": affected, "preview": preview})


@bp.get("/api/module-acl/export")
@admin_required
def api_module_acl_export():
    """导出模块权限矩阵为 Excel（用户 × 模块 四勾选）。"""
    db = get_db()
    users = {u["id"]: dict(u) for u in db.execute(
        "SELECT id, username, display_name FROM users").fetchall()}
    rows = db.execute(
        "SELECT * FROM module_acl WHERE subject_type=? ORDER BY module_key, subject_id",
        (SUBJECT_TYPE_USER,),
    ).fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "模块权限矩阵"
    headers = ["模块", "主体ID", "工号", "姓名", "可见性", "读", "写", "管理"]
    ws.append(headers)
    for r in rows:
        u = users.get(r["subject_id"], {})
        ws.append([r["module_key"], r["subject_id"], u.get("username", ""), u.get("display_name", ""),
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
