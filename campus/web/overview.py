# -*- coding: utf-8 -*-
"""全局总览接口（具备「全局总览」模块读权限的用户）。"""
from flask import Blueprint, jsonify

from campus.db.connection import get_db
from campus.services.overview_stats import build_overview_payload
from campus.web.guards import module_read_required

bp = Blueprint("overview", __name__)


@bp.get("/api/overview")
@module_read_required("overview")
def api_overview():
    return jsonify(build_overview_payload(get_db()))
