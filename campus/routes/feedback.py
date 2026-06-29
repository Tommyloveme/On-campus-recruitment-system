# -*- coding: utf-8 -*-
"""问题反馈：全员可查看与回复进展；管理员可设优先级、回复、删除。"""
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
PRIORITY_LABELS = {
    "low": "低",
    "normal": "中",
    "high": "高",
    "urgent": "紧急",
}
VALID_PRIORITIES = set(PRIORITY_LABELS)


def _sanitize_html(html):
    text = str(html or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<iframe[^>]*>.*?</iframe>", "", text)
    text = re.sub(r"(?i)\son\w+\s*=", " data-removed=", text)
    return text.strip()


def _row_to_dict(row):
    pri = row["priority"] if "priority" in row.keys() else "normal"
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "title": row["title"] if "title" in row.keys() else "",
        "content_html": row["content_html"],
        "priority": pri,
        "priority_label": PRIORITY_LABELS.get(pri, pri),
        "reply_html": (row["reply_html"] if "reply_html" in row.keys() else "") or "",
        "reply_by": (row["reply_by"] if "reply_by" in row.keys() else "") or "",
        "reply_at": (row["reply_at"] if "reply_at" in row.keys() else "") or "",
        "created_at": row["created_at"],
        "is_mine": row["user_id"] == g.user["id"],
    }


def _priority_order_clause(order):
    asc = order == "asc"
    return (
        "CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 "
        "WHEN 'normal' THEN 3 WHEN 'low' THEN 4 ELSE 5 END ASC, created_at DESC"
        if asc
        else "CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 "
             "WHEN 'normal' THEN 3 WHEN 'low' THEN 4 ELSE 5 END ASC, created_at DESC"
    )


@bp.get("/api/feedback")
@login_required
def api_feedback_list():
    page = max(1, int(request.args.get("page", 1)))
    fetch_all = request.args.get("all") == "1"
    size = min(2000, max(1, int(request.args.get("size", 20))))
    sort = (request.args.get("sort") or "created_at").strip()
    order = (request.args.get("order") or "desc").strip().lower()
    if sort not in ("created_at", "priority", "id"):
        sort = "created_at"
    order_sql = "ASC" if order == "asc" else "DESC"
    if sort == "priority":
        order_clause = _priority_order_clause(order)
    else:
        order_clause = f"{sort} {order_sql}"

    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()["c"]
    if fetch_all:
        size = max(total, 1)
        page = 1
    rows = db.execute(
        f"SELECT * FROM feedback ORDER BY {order_clause} LIMIT ? OFFSET ?",
        (size, (page - 1) * size),
    ).fetchall()
    return jsonify({
        "items": [_row_to_dict(r) for r in rows],
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
    content = _sanitize_html(body.get("content_html"))
    if not title:
        return jsonify({"error": "请填写反馈标题"}), 400
    if not content:
        return jsonify({"error": "反馈内容不能为空"}), 400
    db = get_db()
    ts = now_str()
    cur = db.execute(
        "INSERT INTO feedback (user_id, username, display_name, title, content_html, "
        "priority, reply_html, reply_by, reply_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (g.user["id"], g.user["username"], g.user["display_name"], title, content,
         "normal", "", "", None, ts),
    )
    db.commit()
    log.info("问题反馈 %s id=%d title=%s", who(g.user), cur.lastrowid, title)
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.patch("/api/feedback/<int:fid>")
@login_required
def api_feedback_update(fid):
    if not is_admin(g.user):
        return jsonify({"error": "仅系统管理员可设置优先级或回复"}), 403
    body = request.get_json(force=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM feedback WHERE id=?", (fid,)).fetchone()
    if not row:
        return jsonify({"error": "反馈不存在"}), 404

    updates = []
    params = []
    if "priority" in body:
        pri = (body.get("priority") or "").strip()
        if pri not in VALID_PRIORITIES:
            return jsonify({"error": "优先级不合法"}), 400
        updates.append("priority=?")
        params.append(pri)
    if "reply_html" in body:
        reply = _sanitize_html(body.get("reply_html"))
        updates.append("reply_html=?")
        params.append(reply)
        updates.append("reply_by=?")
        params.append(g.user["display_name"])
        updates.append("reply_at=?")
        params.append(now_str())
    if not updates:
        return jsonify({"error": "无有效更新字段"}), 400
    params.append(fid)
    db.execute(f"UPDATE feedback SET {', '.join(updates)} WHERE id=?", params)
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/feedback/<int:fid>")
@login_required
def api_feedback_delete(fid):
    db = get_db()
    row = db.execute("SELECT * FROM feedback WHERE id=?", (fid,)).fetchone()
    if not row:
        return jsonify({"error": "反馈不存在"}), 404
    if not is_admin(g.user) and row["user_id"] != g.user["id"]:
        return jsonify({"error": "无权限删除该反馈"}), 403
    db.execute("DELETE FROM feedback WHERE id=?", (fid,))
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
