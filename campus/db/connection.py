# -*- coding: utf-8 -*-
"""SQLite 连接管理（每请求独立连接）。"""
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
