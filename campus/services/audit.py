# -*- coding: utf-8 -*-
"""操作审计日志的写入与查询（全系统唯一入口，各页面日志标签页复用）。

- add_log(module=...)：登记操作所属模块（module_key，与模块注册表一致），
  各操作页面的「日志」标签页据此过滤展示。
- query_logs(module=...)：module 为 None 查全量（管理员审计），否则按模块过滤。
"""
from campus.db.connection import get_db, now_str


def add_log(user, action, message, candidate_id=None, candidate_name=None, group_id=None,
            module=None):
    get_db().execute(
        "INSERT INTO logs (user_name, action, candidate_id, candidate_name, group_id, "
        "module_key, message, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user["display_name"], action, candidate_id, candidate_name, group_id,
         module or "", message, now_str()),
    )


def query_logs(db, page, size, module=None):
    """分页查询操作日志（倒序）；module 非空时仅查该模块的日志。"""
    where, args = "", []
    if module:
        where = " WHERE module_key=?"
        args.append(module)
    total = db.execute(f"SELECT COUNT(*) AS c FROM logs{where}", args).fetchone()["c"]
    rows = db.execute(
        f"SELECT * FROM logs{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    return total, [dict(r) for r in rows]
