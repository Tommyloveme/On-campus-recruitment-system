# -*- coding: utf-8 -*-
"""操作日志查询接口（合并入「权限管理」页，仅系统管理员）。"""
from flask import Blueprint, jsonify, request

from campus.core.settings import APP_CONFIG
from campus.db.connection import get_db
from campus.services.audit import query_logs
from campus.web.guards import admin_required

bp = Blueprint("logs", __name__)


@bp.get("/api/logs")
@admin_required
def api_logs():
    page = max(1, request.args.get("page", 1, type=int))
    size = APP_CONFIG["logs"]["page_size"]
    total, items = query_logs(get_db(), page, size)
    return jsonify({"total": total, "page": page, "size": size, "items": items})
