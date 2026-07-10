# -*- coding: utf-8 -*-
"""操作日志查询接口。

- 不带 module：全量日志，仅系统管理员（全局审计）。
- 带 module=<模块key>：该模块日志，具备该模块读权限即可（各页面日志标签页）。
- 结果按查看者日志权限（users.log_level，1 最高 10 最低）过滤：
  只返回 level >= 查看者权限值的日志；管理员恒为 1（全部可见）。
- DELETE /api/logs：管理员清理全量日志 / 指定模块日志，或某时间点之后的日志。
"""
from flask import Blueprint, g, jsonify, request

from campus.core.log_levels import clamp_log_level
from campus.core.modules import MODULE_REGISTRY, module_entry, module_keys
from campus.core.settings import APP_CONFIG
from campus.db.connection import get_db
from campus.services.acl import is_admin, module_readable_for
from campus.services.audit import add_log, delete_logs, query_logs
from campus.web.guards import admin_required, login_required

bp = Blueprint("logs", __name__)


def viewer_log_level(user):
    """查看者日志权限：管理员恒为 1；其余取 users.log_level（默认 10）。"""
    if is_admin(user):
        return 1
    keys = user.keys() if hasattr(user, "keys") else []
    return clamp_log_level(user["log_level"] if "log_level" in keys else None)


def _flat_modules():
    """扁平模块列表（含板块），供日志清理下拉使用。"""
    out = []

    def walk(entry):
        out.append({"key": entry["key"], "label": entry["label"], "type": entry.get("type", "item")})
        for child in entry.get("items") or []:
            walk(child)

    for e in MODULE_REGISTRY:
        walk(e)
    return out


@bp.get("/api/logs")
@login_required
def api_logs():
    module = (request.args.get("module") or "").strip() or None
    if module:
        if module not in module_keys():
            return jsonify({"error": "module 不合法"}), 400
        if not (is_admin(g.user) or module_readable_for(g.user, module)):
            return jsonify({"error": "无该模块的日志查看权限"}), 403
    elif not is_admin(g.user):
        return jsonify({"error": "仅系统管理员可查看全量日志"}), 403

    page = max(1, request.args.get("page", 1, type=int))
    allowed = APP_CONFIG.get("logs", {}).get("page_size_options") or [15, 30, 50, 100]
    default_size = APP_CONFIG["logs"].get("page_size", 15)
    size = request.args.get("size", type=int) or default_size
    if size not in allowed:
        size = default_size if default_size in allowed else max(allowed)
    size = min(100, max(1, size))
    total, items = query_logs(get_db(), page, size, module=module,
                              viewer_level=viewer_log_level(g.user))
    return jsonify({"total": total, "page": page, "size": size, "items": items})


@bp.get("/api/logs/modules")
@admin_required
def api_log_modules():
    """日志清理可选模块列表。"""
    return jsonify({"modules": _flat_modules()})


@bp.delete("/api/logs")
@admin_required
def api_logs_delete():
    """删除全量日志 / 指定模块日志，或某时间点之后的日志。

    Body: { module?: 模块key, after?: "YYYY-MM-DD HH:MM:SS" 或 "YYYY-MM-DDTHH:MM" }
    - 不传 module：删除全部日志
    - 不传 after：删除目标全部日志
    - 传 after：删除 created_at >= after 的日志
    """
    body = request.get_json(force=True) or {}
    module = (body.get("module") or "").strip()
    if module and module not in module_keys():
        return jsonify({"error": "请选择有效的模块"}), 400
    after = (body.get("after") or "").strip() or None
    if after:
        after = after.replace("T", " ")
        if len(after) == 16:
            after += ":00"
    db = get_db()
    deleted = delete_logs(db, module=module or None, after=after)
    label = (module_entry(module) or {}).get("label") if module else "全部日志"
    scope = f"「{label}」全部" if not after else f"「{label}」自 {after} 起"
    add_log(g.user, "delete",
            f"{g.user['display_name']} 清理了{scope}日志（{deleted} 条）",
            module="op_logs", level=1)
    db.commit()
    return jsonify({"ok": True, "deleted": deleted, "module": module, "after": after})


@bp.get("/api/logs/levels")
@admin_required
def api_log_levels():
    """各用户日志权限一览（管理看板·操作日志页配置用）。"""
    from campus.core.roles_store import role_label
    rows = get_db().execute(
        "SELECT id, username, display_name, role, log_level FROM users ORDER BY log_level, id"
    ).fetchall()
    return jsonify([{
        "id": r["id"],
        "username": r["username"],
        "display_name": r["display_name"],
        "role": r["role"],
        "role_label": role_label(r["role"]),
        "log_level": 1 if is_admin(r) else clamp_log_level(r["log_level"]),
    } for r in rows])


@bp.put("/api/logs/levels/<int:uid>")
@admin_required
def api_log_level_update(uid):
    """设置某用户的日志权限（1-10，1 最高）。"""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    if is_admin(user):
        db.execute("UPDATE users SET log_level=1 WHERE id=?", (uid,))
        add_log(g.user, "permission",
                f"{g.user['display_name']} 尝试调整系统管理员「{user['display_name']}」日志权限，系统已保持为 L1",
                module="op_logs", level=1)
        db.commit()
        return jsonify({"ok": True, "id": uid, "log_level": 1})
    raw = (request.get_json(force=True) or {}).get("log_level")
    try:
        level = int(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "log_level 须为 1-10 的整数"}), 400
    if not 1 <= level <= 10:
        return jsonify({"error": "log_level 须为 1-10 的整数"}), 400
    db.execute("UPDATE users SET log_level=? WHERE id=?", (level, uid))
    add_log(g.user, "permission",
            f"{g.user['display_name']} 将「{user['display_name']}」的日志权限调整为 {level}",
            module="op_logs", level=1)
    db.commit()
    return jsonify({"ok": True, "id": uid, "log_level": level})
