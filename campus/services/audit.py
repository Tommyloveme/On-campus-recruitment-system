# -*- coding: utf-8 -*-
"""操作审计日志的写入与查询。"""
from campus.db.connection import get_db, now_str


def add_log(user, action, message, candidate_id=None, candidate_name=None, group_id=None):
    get_db().execute(
        "INSERT INTO logs (user_name, action, candidate_id, candidate_name, group_id, message, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (user["display_name"], action, candidate_id, candidate_name, group_id, message, now_str()),
    )


def query_logs(db, page, size):
    """分页查询操作日志（倒序）。"""
    total = db.execute("SELECT COUNT(*) AS c FROM logs").fetchone()["c"]
    rows = db.execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT ? OFFSET ?",
        [size, (page - 1) * size],
    ).fetchall()
    return total, [dict(r) for r in rows]
