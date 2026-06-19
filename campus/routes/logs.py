# -*- coding: utf-8 -*-
"""操作日志查询接口。"""
from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.auth.permissions import GLOBAL_VIEW_ROLES
from campus.db.connection import get_db
from campus.settings import APP_CONFIG

bp = Blueprint("logs", __name__)


@bp.get("/api/logs")
@login_required
def api_logs():
    page = max(1, request.args.get("page", 1, type=int))
    size = APP_CONFIG["logs"]["page_size"]
    db = get_db()
    where, params = "", []
    if g.user["role"] not in GLOBAL_VIEW_ROLES:
        where = "WHERE group_id=? OR group_id IS NULL"
        params.append(g.user["group_id"] or -1)
    total = db.execute(f"SELECT COUNT(*) AS c FROM logs {where}", params).fetchone()["c"]
    rows = db.execute(
        f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    ).fetchall()
    return jsonify({"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]})
