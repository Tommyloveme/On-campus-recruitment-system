# -*- coding: utf-8 -*-
"""问题反馈：用户提交富文本反馈，管理员在管理看板查看。"""
import os
import re
import uuid

from flask import Blueprint, g, jsonify, request, send_file

from campus.auth.decorators import login_required
from campus.db.connection import get_db, now_str
from campus.logging_util import log, who
from campus.services.acl import is_admin
from campus.settings import FEEDBACK_DIR

bp = Blueprint("feedback", __name__)

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _sanitize_html(html):
    text = str(html or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<iframe[^>]*>.*?</iframe>", "", text)
    text = re.sub(r"(?i)\son\w+\s*=", " data-removed=", text)
    return text.strip()


def _row_to_dict(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "content_html": row["content_html"],
        "created_at": row["created_at"],
    }


@bp.get("/api/feedback")
@login_required
def api_feedback_list():
    if not is_admin(g.user):
        return jsonify({"error": "仅系统管理员可查看问题反馈"}), 403
    page = max(1, int(request.args.get("page", 1)))
    size = min(100, max(1, int(request.args.get("size", 20))))
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()["c"]
    rows = db.execute(
        "SELECT * FROM feedback ORDER BY id DESC LIMIT ? OFFSET ?",
        (size, (page - 1) * size),
    ).fetchall()
    return jsonify({
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "size": size,
    })


@bp.post("/api/feedback")
@login_required
def api_feedback_create():
    body = request.get_json(force=True) or {}
    content = _sanitize_html(body.get("content_html"))
    if not content:
        return jsonify({"error": "反馈内容不能为空"}), 400
    db = get_db()
    ts = now_str()
    cur = db.execute(
        "INSERT INTO feedback (user_id, username, display_name, content_html, created_at) "
        "VALUES (?,?,?,?,?)",
        (g.user["id"], g.user["username"], g.user["display_name"], content, ts),
    )
    db.commit()
    log.info("问题反馈 %s id=%d", who(g.user), cur.lastrowid)
    return jsonify({"ok": True, "id": cur.lastrowid})


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
