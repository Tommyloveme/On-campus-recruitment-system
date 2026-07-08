# -*- coding: utf-8 -*-
"""简历上传、下载、预览与批量导出。"""
import io
import json
import os
import zipfile
from datetime import datetime

from flask import Blueprint, g, jsonify, request, send_file

from campus.core.logging_util import log, who
from campus.core.settings import RESUME_DIR
from campus.db.connection import get_db, now_str
from campus.db.field_store import field_get
from campus.services.acl import can_see_candidate
from campus.services.audit import add_log
from campus.services.resumes import (
    get_candidate_or_403,
    new_resume_stored_name,
    PREVIEW_PAGE,
    remove_resume_file,
)
from campus.web.guards import login_required

bp = Blueprint("resumes", __name__)


@bp.post("/api/candidates/<int:cid>/resume")
@login_required
def api_resume_upload(cid):
    row, err = get_candidate_or_403(cid)
    if err:
        return err
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择简历文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if not ext:
        ext = ".bin"
    os.makedirs(RESUME_DIR, exist_ok=True)
    stored = new_resume_stored_name(cid, ext)
    f.save(os.path.join(RESUME_DIR, stored))
    remove_resume_file(row["resume_file"])

    db = get_db()
    db.execute("UPDATE candidates SET resume_file=?, resume_name=?, updated_at=? WHERE id=?",
               (stored, f.filename, now_str(), cid))
    name = field_get(json.loads(row["data"]), "name")
    verb = "更新" if row["resume_file"] else "上传"
    add_log(g.user, "update", f"{g.user['display_name']} {verb}了「{name}」的简历（{f.filename}）",
            cid, name, row["group_id"], module="registration")
    db.commit()
    log.info("简历%s %s cid=%d name=%s file=%s", verb, who(g.user), cid, name, f.filename)
    return jsonify({"ok": True, "resume_name": f.filename})


@bp.get("/api/candidates/<int:cid>/resume")
@login_required
def api_resume_download(cid):
    row, err = get_candidate_or_403(cid, need="view")
    if err:
        return err
    if not row["resume_file"]:
        return jsonify({"error": "该候选人尚未上传简历"}), 404
    path = os.path.join(RESUME_DIR, row["resume_file"])
    if not os.path.exists(path):
        return jsonify({"error": "简历文件丢失，请重新上传"}), 404
    name = field_get(json.loads(row["data"]), "name")
    ext = os.path.splitext(row["resume_name"])[1]
    return send_file(path, as_attachment=True, download_name=f"{name}_{os.path.splitext(row['resume_name'])[0]}{ext}")


@bp.get("/api/candidates/<int:cid>/resume/preview")
@login_required
def api_resume_preview(cid):
    row, err = get_candidate_or_403(cid, need="view")
    if err:
        return err
    if not row["resume_file"]:
        return jsonify({"error": "该候选人尚未上传简历"}), 404
    path = os.path.join(RESUME_DIR, row["resume_file"])
    if not os.path.exists(path):
        return jsonify({"error": "简历文件丢失，请重新上传"}), 404

    ext = os.path.splitext(row["resume_file"])[1].lower()
    if ext == ".pdf":
        return send_file(path, mimetype="application/pdf", as_attachment=False,
                         download_name=row["resume_name"])
    try:
        import mammoth
        with open(path, "rb") as f:
            html = mammoth.convert_to_html(f).value
    except Exception:
        return jsonify({"error": "简历解析失败，请下载原文件查看"}), 500
    name = field_get(json.loads(row["data"]), "name")
    return PREVIEW_PAGE.format(title=f"{name} - {row['resume_name']}", content=html)


@bp.delete("/api/candidates/<int:cid>/resume")
@login_required
def api_resume_delete(cid):
    row, err = get_candidate_or_403(cid, need="delete")
    if err:
        return err
    if not row["resume_file"]:
        return jsonify({"error": "该候选人没有简历"}), 400
    remove_resume_file(row["resume_file"])
    db = get_db()
    db.execute("UPDATE candidates SET resume_file=NULL, resume_name=NULL, updated_at=? WHERE id=?",
               (now_str(), cid))
    name = field_get(json.loads(row["data"]), "name")
    add_log(g.user, "delete", f"{g.user['display_name']} 删除了「{name}」的简历（{row['resume_name']}）",
            cid, name, row["group_id"], module="registration")
    db.commit()
    log.info("删除简历 %s cid=%d name=%s", who(g.user), cid, name)
    return jsonify({"ok": True})


@bp.post("/api/resumes/export")
@login_required
def api_resumes_export():
    ids = request.get_json(force=True).get("ids") or []
    if not ids:
        return jsonify({"error": "请先勾选候选人"}), 400
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()

    buf = io.BytesIO()
    exported, used_names = 0, set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            if not can_see_candidate(db, g.user, row) or not row["resume_file"]:
                continue
            path = os.path.join(RESUME_DIR, row["resume_file"])
            if not os.path.exists(path):
                continue
            name = field_get(json.loads(row["data"]), "name") or "未命名"
            arcname = f"{name}_{row['resume_name']}"
            if arcname in used_names:
                arcname = f"{name}_{row['id']}_{row['resume_name']}"
            used_names.add(arcname)
            zf.write(path, arcname)
            exported += 1
    if exported == 0:
        return jsonify({"error": "选中的候选人均没有可导出的简历"}), 400

    add_log(g.user, "export", f"{g.user['display_name']} 批量导出了 {exported} 份简历", module="registration")
    db.commit()
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    resp = send_file(buf, as_attachment=True, download_name=f"简历导出_{ts}.zip",
                     mimetype="application/zip")
    resp.headers["X-Export-Count"] = str(exported)
    return resp
