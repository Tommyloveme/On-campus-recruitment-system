# -*- coding: utf-8 -*-
"""全局总览接口（具备「全局总览」模块读权限的用户）。"""
import json

from flask import Blueprint, g, jsonify

from campus.auth.decorators import login_required
from campus.db.connection import get_db
from campus.services.acl import module_readable_for
from campus.services.candidates import candidate_dict

bp = Blueprint("overview", __name__)


@bp.get("/api/overview")
@login_required
def api_overview():
    if not module_readable_for(g.user, "overview"):
        return jsonify({"error": "无「全局总览」模块的访问权限"}), 403
    db = get_db()
    rows = db.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    cands = []
    stats = {"total": len(rows), "signed": 0, "onboarded": 0, "high_risk": 0}
    for r in rows:
        c = candidate_dict(r)
        log_row = db.execute(
            "SELECT message, created_at FROM logs WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (r["id"],)
        ).fetchone()
        c["latest_log"] = (f"[{log_row['created_at']}] {log_row['message']}" if log_row else "暂无更新记录")
        cands.append(c)
        d = c["data"]
        if d.get("sign_status") == "已签约":
            stats["signed"] += 1
        if d.get("onboarded") == "是":
            stats["onboarded"] += 1
        if d.get("onboard_risk") == "高":
            stats["high_risk"] += 1
    return jsonify([{
        "group_id": None,
        "group_name": "全部候选人",
        "stats": stats,
        "candidates": cands,
    }])
