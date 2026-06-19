# -*- coding: utf-8 -*-
"""数据库备份与恢复。"""
import os
import re
import sqlite3
import time
from datetime import datetime

from campus.logging_util import log
from campus.settings import APP_CONFIG, BACKUP_DIR, DB_PATH

BACKUP_NAME_RE = re.compile(r"^backup_\d{8}_\d{6}(_\d{3})?(_manual)?\.db$")


def take_backup(manual=False):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now()
    name = ("backup_" + ts.strftime("%Y%m%d_%H%M%S") + f"_{ts.microsecond // 1000:03d}"
            + ("_manual" if manual else "") + ".db")
    path = os.path.join(BACKUP_DIR, name)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    prune_backups()
    log.debug("数据库备份完成 %s manual=%s", name, manual)
    return name


def prune_backups():
    retention_days = APP_CONFIG.get("backup", {}).get("retention_days", 3)
    cutoff = time.time() - retention_days * 86400
    for f in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, f)
        if BACKUP_NAME_RE.match(f) and os.path.getmtime(path) < cutoff:
            os.remove(path)


def backup_scheduler():
    interval = APP_CONFIG.get("backup", {}).get("interval_hours", 1) * 3600
    while True:
        try:
            name = take_backup()
            log.info("自动备份完成 %s", name)
        except Exception as e:
            log.error("自动备份失败: %s", e)
        time.sleep(interval)
