# -*- coding: utf-8 -*-
"""数据库备份与恢复（列表/创建/清理/恢复/定时调度均在此，web 层不做文件与 SQL 操作）。"""
import os
import re
import sqlite3
import time
from datetime import datetime

from campus.core.logging_util import log
from campus.core.settings import APP_CONFIG, BACKUP_DIR, DB_PATH

BACKUP_NAME_RE = re.compile(r"^backup_\d{8}_\d{6}(_\d{3})?(_manual)?\.db$")


def list_backups():
    """备份文件清单（按名称倒序，即时间近者在前）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    items = []
    for f in os.listdir(BACKUP_DIR):
        if not BACKUP_NAME_RE.match(f):
            continue
        path = os.path.join(BACKUP_DIR, f)
        items.append({
            "name": f,
            "manual": "_manual" in f,
            "time": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
            "size_kb": round(os.path.getsize(path) / 1024, 1),
        })
    items.sort(key=lambda x: x["name"], reverse=True)
    return items


def restore_backup(name):
    """将指定备份覆盖回主库；恢复前自动保存安全备份，返回其名称。

    调用方须先用 BACKUP_NAME_RE 校验 name 并确认文件存在。
    """
    path = os.path.join(BACKUP_DIR, name)
    safety = take_backup(manual=True)
    src = sqlite3.connect(path)
    dst = sqlite3.connect(DB_PATH)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    return safety


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
