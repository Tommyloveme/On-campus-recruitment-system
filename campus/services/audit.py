# -*- coding: utf-8 -*-
"""操作审计日志的写入与查询（全系统唯一入口，各页面日志标签页复用）。

- add_log(module=...)：登记操作所属模块（module_key，与模块注册表一致），
  各操作页面的「日志」标签页据此过滤展示。
- add_log(level=...)：日志等级 1-10（1 最敏感）；缺省按动作类型取
  campus.core.log_levels.DEFAULT_ACTION_LEVELS。
- query_logs(module=..., viewer_level=...)：module 为 None 查全量（管理员审计），
  否则按模块过滤；viewer_level 为查看者日志权限，只返回 level >= viewer_level 的日志。
- delete_logs / purge_logs：管理员清理指定模块全量日志，或某时间点之后的日志。
"""
from campus.core.log_levels import clamp_log_level, default_level_for_action
from campus.db.connection import get_db, now_str


def add_log(user, action, message, candidate_id=None, candidate_name=None, group_id=None,
            module=None, level=None):
    level = clamp_log_level(level, default=default_level_for_action(action))
    get_db().execute(
        "INSERT INTO logs (user_name, action, candidate_id, candidate_name, group_id, "
        "module_key, level, message, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (user["display_name"], action, candidate_id, candidate_name, group_id,
         module or "", level, message, now_str()),
    )


def query_logs(db, page, size, module=None, viewer_level=1):
    """分页查询操作日志（倒序）；module 非空时仅查该模块的日志，
    并按查看者日志权限过滤（只可见 level >= viewer_level 的日志）。"""
    conds, args = ["level >= ?"], [clamp_log_level(viewer_level, default=1)]
    if module:
        conds.append("module_key=?")
        args.append(module)
    where = " WHERE " + " AND ".join(conds)
    total = db.execute(f"SELECT COUNT(*) AS c FROM logs{where}", args).fetchone()["c"]
    rows = db.execute(
        f"SELECT * FROM logs{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    return total, [dict(r) for r in rows]


def delete_logs(db, module=None, after=None):
    """删除日志。module 为空则删全量；after 为空则删目标全部；
    否则删 created_at >= after 的记录。
    返回删除条数。"""
    module = (module or "").strip()
    after = (after or "").strip() or None
    conds, args = [], []
    if module:
        conds.append("module_key=?")
        args.append(module)
    if after:
        conds.append("created_at>=?")
        args.append(after)
    if conds:
        cur = db.execute(
            "DELETE FROM logs WHERE " + " AND ".join(conds),
            args,
        )
    else:
        cur = db.execute("DELETE FROM logs")
    return cur.rowcount or 0


# 兼容旧名
purge_logs = delete_logs
