# -*- coding: utf-8 -*-
"""SQLite 连接管理（每请求独立连接，绑定在 Flask g 上）。

并发模型（与 waitress 多线程配合，支撑 500+ 并发用户）：
- WAL 日志模式在建库时开启（campus/db/schema.py init_db），读写不互斥；
- busy_timeout=10s：写锁竞争时等待而非直接报错；
- candidates.phone 唯一索引兜底防止并发重复建档（见 services/candidate_pipeline.py）。

非 Flask 场景（scripts/、tests/）需自行 sqlite3.connect，勿依赖 g。
"""
import sqlite3
from datetime import datetime

from flask import g

from campus.core.settings import DB_PATH


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def register_db(app):
    app.teardown_appcontext(close_db)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
