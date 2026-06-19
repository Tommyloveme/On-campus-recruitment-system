# -*- coding: utf-8 -*-
"""全局总览接口（管理员/全局查看员）。"""
from flask import Blueprint, g, jsonify

from campus.auth.decorators import login_required
from campus.auth.permissions import GLOBAL_VIEW_ROLES
from campus.db.connection import get_db
from campus.services.candidates import candidate_dict, group_name_map

bp = Blueprint("overview", __name__)


@bp.get("/api/overview")
@login_required
def api_overview():
    if g.user["role"] not in GLOBAL_VIEW_ROLES:
        return jsonify({"error": "需要管理员或全局查看员权限"}), 403
    db = get_db()
    names = group_name_map()
    groups = []
    for gid, gname in names.items():
        rows = db.execute("SELECT * FROM candidates WHERE group_id=? ORDER BY updated_at DESC", (gid,)).fetchall()
        cands = []
        stats = {"total": len(rows), "signed": 0, "onboarded": 0, "high_risk": 0}
        for r in rows:
            c = candidate_dict(r, names)
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
        groups.append({"group_id": gid, "group_name": gname, "stats": stats, "candidates": cands})
    return jsonify(groups)
