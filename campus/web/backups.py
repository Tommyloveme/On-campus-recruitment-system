# -*- coding: utf-8 -*-
"""数据备份与恢复接口（仅管理员）；文件与数据库操作在 services.backups。"""
import os

from flask import Blueprint, g, jsonify, request

from campus.core.logging_util import log, who
from campus.core.settings import BACKUP_DIR
from campus.db.connection import get_db
from campus.services.audit import add_log
from campus.services.backups import BACKUP_NAME_RE, list_backups, restore_backup, take_backup
from campus.web.guards import admin_required

bp = Blueprint("backups", __name__)


@bp.get("/api/backups")
@admin_required
def api_backups():
    return jsonify(list_backups())


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
    if not os.path.exists(os.path.join(BACKUP_DIR, name)):
        return jsonify({"error": "备份文件不存在"}), 404

    safety = restore_backup(name)

    add_log(g.user, "backup", f"{g.user['display_name']} 将数据恢复至备份「{name}」（恢复前状态已自动保存为 {safety}）")
    get_db().commit()
    log.info("恢复备份 %s target=%s safety=%s", who(g.user), name, safety)
    return jsonify({"ok": True, "restored": name, "safety_backup": safety})
