# -*- coding: utf-8 -*-
"""数据备份与恢复接口（仅管理员）。"""
import os
import sqlite3
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import admin_required
from campus.db.connection import get_db
from campus.logging_util import log, who
from campus.services.audit import add_log
from campus.services.backups import BACKUP_NAME_RE, take_backup
from campus.settings import BACKUP_DIR, DB_PATH

bp = Blueprint("backups", __name__)


@bp.get("/api/backups")
@admin_required
def api_backups():
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
    return jsonify(items)


@bp.post("/api/backups")
@admin_required
def api_backup_create():
    name = take_backup(manual=True)
    add_log(g.user, "backup", f"{g.user['display_name']} 手动创建了数据备份（{name}）")
    get_db().commit()
    log.info("手动备份 %s file=%s", who(g.user), name)
    return jsonify({"ok": True, "name": name})


@bp.post("/api/backups/restore")
@admin_required
def api_backup_restore():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not BACKUP_NAME_RE.match(name):
        return jsonify({"error": "备份文件名不合法"}), 400
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(path):
        return jsonify({"error": "备份文件不存在"}), 404

    safety = take_backup(manual=True)

    src = sqlite3.connect(path)
    dst = sqlite3.connect(DB_PATH)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()

    add_log(g.user, "backup", f"{g.user['display_name']} 将数据恢复至备份「{name}」（恢复前状态已自动保存为 {safety}）")
    get_db().commit()
    log.info("恢复备份 %s target=%s safety=%s", who(g.user), name, safety)
    return jsonify({"ok": True, "restored": name, "safety_backup": safety})
