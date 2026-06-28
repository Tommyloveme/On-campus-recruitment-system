# -*- coding: utf-8 -*-
"""操作日志查询接口（具备「操作日志」模块读权限的用户）。"""
from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.db.connection import get_db
from campus.services.acl import module_readable_for
from campus.settings import APP_CONFIG

bp = Blueprint("logs", __name__)


@bp.get("/api/logs")
@login_required
def api_logs():
    if not module_readable_for(g.user, "logs"):
        return jsonify({"error": "无「操作日志」模块的访问权限"}), 403
    page = max(1, request.args.get("page", 1, type=int))
    size = APP_CONFIG["logs"]["page_size"]
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM logs").fetchone()["c"]
    rows = db.execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT ? OFFSET ?",
        [size, (page - 1) * size],
    ).fetchall()
    return jsonify({"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]})
