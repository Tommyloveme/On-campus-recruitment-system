# -*- coding: utf-8 -*-
"""数据汇总总表接口。

- GET /api/data-hub：按 简历编号/来源/子标签/字段 检索总表（登录即可）。
- GET /api/data-hub/ui-values：某子标签 UI 专属列的取值映射（表格渲染用）。
- PUT /api/data-hub/ui-value：写入某候选人的 UI 专属列值（需该子标签模块写权限）。
"""
from flask import Blueprint, g, jsonify, request

from campus.core.stage_config import load_stage_table_config, validate_stage
from campus.db.connection import get_db
from campus.services.acl import module_writable_for
from campus.services.audit import add_log
from campus.services.data_hub import (
    SOURCE_UI,
    query_hub,
    record_hub_fields,
    ui_values_for_tab,
)
from campus.web.guards import login_required

bp = Blueprint("data_hub", __name__)


@bp.get("/api/data-hub")
@login_required
def api_data_hub_query():
    rows = query_hub(
        get_db(),
        resume_id=(request.args.get("resume_id") or "").strip() or None,
        source=(request.args.get("source") or "").strip() or None,
        tab=(request.args.get("tab") or "").strip() or None,
        field=(request.args.get("field") or "").strip() or None,
        limit=request.args.get("limit", 2000, type=int),
    )
    return jsonify({"total": len(rows), "items": rows})


@bp.get("/api/data-hub/ui-values")
@login_required
def api_data_hub_ui_values():
    tab = (request.args.get("tab") or "").strip()
    try:
        validate_stage(tab)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"tab": tab, "values": ui_values_for_tab(get_db(), tab)})


@bp.put("/api/data-hub/ui-value")
@login_required
def api_data_hub_ui_value_set():
    b = request.get_json(force=True)
    tab = (b.get("tab") or "").strip()
    resume_key = (b.get("resume_key") or "").strip()
    field_key = (b.get("field_key") or "").strip()
    value = str(b.get("value") if b.get("value") is not None else "")
    try:
        validate_stage(tab)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not resume_key or not field_key:
        return jsonify({"error": "resume_key 与 field_key 不能为空"}), 400
    ui_cols = {c["key"]: c for c in load_stage_table_config(tab).get("ui_columns", [])}
    if field_key not in ui_cols:
        return jsonify({"error": f"「{field_key}」不是该子标签配置的 UI 专属列"}), 400
    if not module_writable_for(g.user, tab):
        return jsonify({"error": "无该子标签的写入权限"}), 403

    db = get_db()
    record_hub_fields(db, SOURCE_UI, tab, resume_key, {field_key: value},
                      label_map={field_key: ui_cols[field_key].get("label", field_key)},
                      user_name=g.user["display_name"])
    add_log(g.user, "update",
            f"{g.user['display_name']} 更新了 {tab} 页 UI 列「{ui_cols[field_key].get('label', field_key)}」"
            f"（{resume_key}）：{value or '空'}", module=tab)
    db.commit()
    return jsonify({"ok": True})
