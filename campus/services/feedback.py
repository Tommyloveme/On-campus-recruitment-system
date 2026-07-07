# -*- coding: utf-8 -*-
"""问题反馈业务：列表/创建/更新/删除与 HTML 清洗（SQL 收敛于此）。"""
import re

from campus.db.connection import now_str

PRIORITY_LABELS = {
    "low": "低",
    "normal": "中",
    "high": "高",
    "urgent": "紧急",
}
VALID_PRIORITIES = set(PRIORITY_LABELS)

_PRIORITY_ORDER_SQL = (
    "CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 "
    "WHEN 'normal' THEN 3 WHEN 'low' THEN 4 ELSE 5 END ASC, created_at DESC"
)


def sanitize_html(html):
    text = str(html or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<iframe[^>]*>.*?</iframe>", "", text)
    text = re.sub(r"(?i)\son\w+\s*=", " data-removed=", text)
    return text.strip()


def feedback_row_dict(row, viewer_id):
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
        "is_mine": row["user_id"] == viewer_id,
    }


def list_feedback(db, page, size, sort, order, fetch_all=False):
    """分页查询反馈；返回 (rows, total, page, size)。"""
    if sort not in ("created_at", "priority", "id"):
        sort = "created_at"
    if sort == "priority":
        order_clause = _PRIORITY_ORDER_SQL
    else:
        order_clause = f"{sort} {'ASC' if order == 'asc' else 'DESC'}"
    total = db.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()["c"]
    if fetch_all:
        size = max(total, 1)
        page = 1
    rows = db.execute(
        f"SELECT * FROM feedback ORDER BY {order_clause} LIMIT ? OFFSET ?",
        (size, (page - 1) * size),
    ).fetchall()
    return rows, total, page, size


def create_feedback(db, user, title, content_html):
    cur = db.execute(
        "INSERT INTO feedback (user_id, username, display_name, title, content_html, "
        "priority, reply_html, reply_by, reply_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user["id"], user["username"], user["display_name"], title, content_html,
         "normal", "", "", None, now_str()),
    )
    return cur.lastrowid


def get_feedback(db, fid):
    return db.execute("SELECT * FROM feedback WHERE id=?", (fid,)).fetchone()


def update_feedback(db, fid, user, priority=None, reply_html=None):
    """管理员更新优先级/回复；返回错误文案或 None。"""
    updates, params = [], []
    if priority is not None:
        if priority not in VALID_PRIORITIES:
            return "优先级不合法"
        updates.append("priority=?")
        params.append(priority)
    if reply_html is not None:
        updates.append("reply_html=?")
        params.append(reply_html)
        updates.append("reply_by=?")
        params.append(user["display_name"])
        updates.append("reply_at=?")
        params.append(now_str())
    if not updates:
        return "无有效更新字段"
    params.append(fid)
    db.execute(f"UPDATE feedback SET {', '.join(updates)} WHERE id=?", params)
    return None


def delete_feedback(db, fid):
    db.execute("DELETE FROM feedback WHERE id=?", (fid,))
