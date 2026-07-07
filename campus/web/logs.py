# -*- coding: utf-8 -*-
"""操作日志查询接口。

- 不带 module：全量日志，仅系统管理员（全局审计）。
- 带 module=<模块key>：该模块日志，具备该模块读权限即可（各页面日志标签页）。
"""
from flask import Blueprint, g, jsonify, request

from campus.core.modules import module_keys
from campus.core.settings import APP_CONFIG
from campus.db.connection import get_db
from campus.services.acl import is_admin, module_readable_for
from campus.services.audit import query_logs
from campus.web.guards import login_required

bp = Blueprint("logs", __name__)


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
    size = request.args.get("size", type=int) or APP_CONFIG["logs"]["page_size"]
    size = min(200, max(1, size))
    total, items = query_logs(get_db(), page, size, module=module)
    return jsonify({"total": total, "page": page, "size": size, "items": items})
