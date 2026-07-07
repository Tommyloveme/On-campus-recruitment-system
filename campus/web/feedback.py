# -*- coding: utf-8 -*-
"""问题反馈接口：全员可查看与回复进展；管理员可设优先级、回复、删除。"""
import os
import uuid

from flask import Blueprint, g, jsonify, request, send_file

from campus.core.logging_util import log, who
from campus.core.settings import FEEDBACK_DIR
from campus.db.connection import get_db
from campus.services.acl import is_admin
from campus.services.feedback import (
    PRIORITY_LABELS,
    create_feedback,
    delete_feedback,
    feedback_row_dict,
    get_feedback,
    list_feedback,
    sanitize_html,
    update_feedback,
)
from campus.web.guards import login_required

bp = Blueprint("feedback", __name__)

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@bp.get("/api/feedback")
@login_required
def api_feedback_list():
    page = max(1, int(request.args.get("page", 1)))
    fetch_all = request.args.get("all") == "1"
    size = min(2000, max(1, int(request.args.get("size", 20))))
    sort = (request.args.get("sort") or "created_at").strip()
    order = (request.args.get("order") or "desc").strip().lower()

    rows, total, page, size = list_feedback(get_db(), page, size, sort, order, fetch_all=fetch_all)
    return jsonify({
        "items": [feedback_row_dict(r, g.user["id"]) for r in rows],
        "total": total,
        "page": page,
        "size": size,
        "is_admin": is_admin(g.user),
        "priority_options": [{"key": k, "label": v} for k, v in PRIORITY_LABELS.items()],
    })


@bp.post("/api/feedback")
@login_required
def api_feedback_create():
    body = request.get_json(force=True) or {}
    title = (body.get("title") or "").strip()
    content = sanitize_html(body.get("content_html"))
    if not title:
        return jsonify({"error": "请填写反馈标题"}), 400
    if not content:
        return jsonify({"error": "反馈内容不能为空"}), 400
    db = get_db()
    fid = create_feedback(db, g.user, title, content)
    db.commit()
    log.info("问题反馈 %s id=%d title=%s", who(g.user), fid, title)
    return jsonify({"ok": True, "id": fid})


@bp.patch("/api/feedback/<int:fid>")
@login_required
def api_feedback_update(fid):
    if not is_admin(g.user):
        return jsonify({"error": "仅系统管理员可设置优先级或回复"}), 403
    body = request.get_json(force=True) or {}
    db = get_db()
    if not get_feedback(db, fid):
        return jsonify({"error": "反馈不存在"}), 404

    priority = (body.get("priority") or "").strip() if "priority" in body else None
    reply_html = sanitize_html(body.get("reply_html")) if "reply_html" in body else None
    err = update_feedback(db, fid, g.user, priority=priority, reply_html=reply_html)
    if err:
        return jsonify({"error": err}), 400
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/feedback/<int:fid>")
@login_required
def api_feedback_delete(fid):
    db = get_db()
    row = get_feedback(db, fid)
    if not row:
        return jsonify({"error": "反馈不存在"}), 404
    if not is_admin(g.user) and row["user_id"] != g.user["id"]:
        return jsonify({"error": "无权限删除该反馈"}), 403
    delete_feedback(db, fid)
    db.commit()
    log.info("删除问题反馈 %s id=%d", who(g.user), fid)
    return jsonify({"ok": True})


@bp.post("/api/feedback/images")
@login_required
def api_feedback_upload_image():
    f = request.files.get("file") or request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "请选择图片文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        return jsonify({"error": "仅支持 PNG、JPG、GIF、WebP 等图片格式"}), 400
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(FEEDBACK_DIR, stored))
    url = f"/api/feedback/images/{stored}"
    return jsonify({"ok": True, "url": url})


@bp.get("/api/feedback/images/<path:name>")
@login_required
def api_feedback_image(name):
    safe = os.path.basename(name)
    path = os.path.join(FEEDBACK_DIR, safe)
    if not os.path.isfile(path):
        return jsonify({"error": "图片不存在"}), 404
    return send_file(path)
