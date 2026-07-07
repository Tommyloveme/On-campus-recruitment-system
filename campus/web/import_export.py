# -*- coding: utf-8 -*-
"""Excel 导入/导出与主数据表导入。"""
import io
import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request, send_file
from openpyxl import Workbook, load_workbook

from campus.core.logging_util import log, who
from campus.core.master_import_config import load_master_import_config
from campus.core.stage_config import (
    get_stage_meta,
    importable_fields,
    load_stage_fields,
    match_import_header,
    validate_stage,
)
from campus.db.connection import get_db
from campus.domain.stage_routing import compute_current_stage
from campus.services.acl import can_see_candidate, is_admin, module_writable_for
from campus.services.audit import add_log
from campus.services.candidate_pipeline import record_manual
from campus.services.master_import import run_dual_master_refresh
from campus.services.master_import_store import (
    both_files_ready,
    detect_source_key,
    get_stored_files,
    load_meta,
    save_upload,
)
from campus.web.guards import login_required

bp = Blueprint("import_export", __name__)


@bp.get("/api/import/template")
@login_required
def api_template():
    stage = request.args.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    fields = importable_fields(stage)
    stage_label = get_stage_meta(stage)["label"]
    wb = Workbook()
    ws = wb.active
    ws.title = stage_label
    for i, f in enumerate(fields, start=1):
        ws.cell(row=1, column=i, value=f["excel_column"])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, len(f["excel_column"]) * 2 + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{stage_label}导入模板.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.post("/api/import")
@login_required
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "请选择Excel文件"}), 400
    stage = request.form.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not module_writable_for(g.user, stage):
        log.warning("Excel导入权限拒绝 %s stage=%s", who(g.user), stage)
        return jsonify({"error": "无该模块的导入权限"}), 403

    try:
        wb = load_workbook(request.files["file"], data_only=True)
    except Exception:
        return jsonify({"error": "文件解析失败，请上传 .xlsx 格式文件"}), 400
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return jsonify({"error": "Excel内容为空"}), 400

    fields = importable_fields(stage)
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    col_map = {}
    for idx, h in enumerate(header):
        for f in fields:
            if match_import_header(f, h):
                col_map[idx] = f["key"]
                break
    if "name" not in col_map.values():
        return jsonify({"error": "Excel中未找到“候选人”列，请参考导入模板"}), 400
    log.debug("Excel导入列映射 %s stage=%s cols=%s", who(g.user), stage, col_map)

    def cell_str(v):
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        return str(v).strip()

    db = get_db()
    from campus.services.candidates import (
        insert_candidate_row,
        normalize_candidate_phone,
        update_candidate_row,
    )
    from campus.services.master_import import build_global_candidate_index
    by_phone = build_global_candidate_index(db)

    created = updated = skipped = 0
    for raw in rows[1:]:
        data = {}
        for idx, key in col_map.items():
            if idx < len(raw):
                data[key] = cell_str(raw[idx])
        if not data.get("name"):
            skipped += 1
            continue
        phone = normalize_candidate_phone(data.get("phone"))
        if not phone:
            skipped += 1
            continue
        data["phone"] = phone
        compute_current_stage(data)
        match = by_phone.get(phone)
        if match:
            old = json.loads(match["data"])
            merged = dict(old)
            changed = False
            for k, v in data.items():
                if v and str(old.get(k, "")) != v:
                    merged[k] = v
                    changed = True
            if changed:
                compute_current_stage(merged)
                update_candidate_row(db, match["id"], merged)
                record_manual(db, phone, merged)
                updated += 1
                match = db.execute("SELECT * FROM candidates WHERE id=?", (match["id"],)).fetchone()
                by_phone[phone] = match
        else:
            cid = insert_candidate_row(db, data, group_id=None)
            record_manual(db, phone, data)
            row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
            by_phone[phone] = row
            created += 1

    stage_label = get_stage_meta(stage)["label"]
    add_log(g.user, "import",
            f"{g.user['display_name']} 通过Excel向{stage_label}导入：新增{created}人，更新{updated}人"
            + (f"，跳过{skipped}行" if skipped else ""), module=stage)
    db.commit()
    log.info("Excel导入 %s stage=%s 新增%d 更新%d 跳过%d",
             who(g.user), stage, created, updated, skipped)
    return jsonify({"ok": True, "created": created, "updated": updated, "skipped": skipped})


@bp.get("/api/master-import/config")
@login_required
def api_master_import_config():
    page = request.args.get("page", "registration")
    try:
        cfg = load_master_import_config(page)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    files = get_stored_files(page, cfg)
    meta = load_meta(page)
    return jsonify({
        "page": cfg.get("page", page),
        "import_mode": cfg.get("import_mode", "dual_file"),
        "join_key": cfg.get("join_key", "resume_id"),
        "match_keys": cfg.get("match_keys", ["phone"]),
        "registration_locked_fields": cfg.get("registration_locked_fields", []),
        "field_mappings": {
            "fields": [
                {
                    "field_key": f.get("field_key"),
                    "ui_label": f.get("ui_label"),
                    "lock_on_import": f.get("lock_on_import", False),
                    "excel_columns": {
                        sk: (f.get("sources") or {}).get(sk, {}).get("excel_column")
                        for sk in (f.get("sources") or {})
                    },
                }
                for f in (cfg.get("field_mappings") or {}).get("fields", [])
            ],
        },
        "file_patterns": cfg.get("file_patterns", {}),
        "sources": [{
            "key": s["key"],
            "label": s["label"],
            "description": s.get("description", ""),
            "pattern": (cfg.get("file_patterns") or {}).get(s["key"], "*"),
            "sheet_name": s.get("sheet_name"),
            "sheet_index": s.get("sheet_index", 0),
            "ready": files.get(s["key"], {}).get("ready", False),
            "original_name": files.get(s["key"], {}).get("original_name"),
            "uploaded_at": files.get(s["key"], {}).get("uploaded_at"),
        } for s in cfg.get("sources", [])],
        "both_ready": both_files_ready(page, cfg),
        "last_refresh": meta.get("last_refresh"),
        "last_refresh_stats": meta.get("last_refresh_stats"),
        "current_stage_field": cfg.get("current_stage_field", "current_stage"),
        "global_import": bool(cfg.get("global_import", True)),
    })


@bp.post("/api/master-import/upload")
@login_required
def api_master_import_upload():
    """上传 Application*.xlsx 或 候选人管理*.xlsx（可一次上传一个或两个）。"""
    page = request.form.get("page", "registration")
    try:
        cfg = load_master_import_config(page)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    uploaded = []
    errors = []
    for key in cfg.get("source_keys", []):
        f = request.files.get(key) or request.files.get(f"file_{key}")
        if not f or not f.filename:
            continue
        try:
            save_upload(page, key, f, f.filename, cfg)
            uploaded.append({"key": key, "filename": f.filename})
        except ValueError as e:
            errors.append(str(e))

    # 兼容单文件字段 file + 自动识别文件名
    f = request.files.get("file")
    if f and f.filename:
        detected = detect_source_key(f.filename, cfg)
        if detected and detected not in [u["key"] for u in uploaded]:
            try:
                save_upload(page, detected, f, f.filename, cfg)
                uploaded.append({"key": detected, "filename": f.filename})
            except ValueError as e:
                errors.append(str(e))
        elif not detected:
            errors.append(f"无法识别文件「{f.filename}」，请使用 Application*.xlsx 或 候选人管理*.xlsx")

    if not uploaded and errors:
        return jsonify({"error": "；".join(errors)}), 400
    if not uploaded:
        return jsonify({"error": "请选择要上传的 Excel 文件"}), 400

    files = get_stored_files(page, cfg)
    meta = load_meta(page)
    add_log(g.user, "import",
            f"{g.user['display_name']} 上传主数据表："
            + "、".join(u["filename"] for u in uploaded), module=page)
    get_db().commit()
    log.info("主数据表上传 %s page=%s files=%s", who(g.user), page, uploaded)
    return jsonify({
        "ok": True,
        "uploaded": uploaded,
        "errors": errors or None,
        "both_ready": both_files_ready(page, cfg),
        "sources": [{
            "key": s["key"],
            "ready": files.get(s["key"], {}).get("ready", False),
            "original_name": files.get(s["key"], {}).get("original_name"),
            "uploaded_at": files.get(s["key"], {}).get("uploaded_at"),
        } for s in cfg.get("sources", [])],
        "last_refresh": meta.get("last_refresh"),
    })


@bp.post("/api/master-import/refresh")
@login_required
def api_master_import_refresh():
    """读取已上传双表，按简历编号关联后全局刷新全部候选人。"""
    page = request.form.get("page", "registration")
    if not request.form and request.is_json:
        page = (request.get_json(silent=True) or {}).get("page", page)

    try:
        cfg = load_master_import_config(page)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not both_files_ready(page, cfg):
        return jsonify({"error": "请先上传 Application*.xlsx 与 候选人管理*.xlsx"}), 400

    db = get_db()
    try:
        created, updated, skipped, stats = run_dual_master_refresh(
            db, cfg, is_admin, g.user)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    add_log(g.user, "import",
            f"{g.user['display_name']} 主数据表刷新：新增{created}人，更新{updated}人"
            + (f"，跳过{skipped}行" if skipped else ""), module=page)
    db.commit()
    log.info("主数据刷新 %s page=%s +%d ~%d skip%d", who(g.user), page, created, updated, skipped)
    return jsonify({
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "stats": stats,
    })


@bp.post("/api/master-import")
@login_required
def api_master_import_legacy():
    """兼容旧接口：单文件上传并立即刷新（建议使用 upload + refresh）。"""
    return jsonify({"error": "请使用 /api/master-import/upload 上传文件，再调用 /api/master-import/refresh 刷新"}), 400


@bp.post("/api/candidates/export")
@login_required
def api_candidates_export():
    b = request.get_json(force=True)
    ids = b.get("ids") or []
    stage = b.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not ids:
        return jsonify({"error": "请先勾选候选人"}), 400
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()

    fields = [f for f in load_stage_fields(stage) if f.get("visible", True)]
    stage_label = get_stage_meta(stage)["label"]

    wb = Workbook()
    ws = wb.active
    ws.title = stage_label
    headers = [f["label"] for f in fields]
    ws.append(headers)
    exported = 0
    for row in rows:
        if not can_see_candidate(get_db(), g.user, row):
            continue
        data = json.loads(row["data"])
        ws.append([data.get(f["key"], "") for f in fields])
        exported += 1
    if exported == 0:
        return jsonify({"error": "选中的候选人均无导出权限"}), 403
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, len(h) * 2 + 4)

    add_log(g.user, "export",
            f"{g.user['display_name']} 从{stage_label}导出了 {exported} 名候选人的Excel数据", module=stage)
    db.commit()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    resp = send_file(buf, as_attachment=True, download_name=f"{stage_label}导出_{ts}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["X-Export-Count"] = str(exported)
    return resp
