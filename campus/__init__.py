# -*- coding: utf-8 -*-
"""校招系统后端模块。"""
import os
import secrets

from flask import Flask

from campus.core.settings import APP_CONFIG, BASE_DIR, SECRET_PATH
from campus.db.connection import register_db
from campus.web import register_routes


def _ensure_secret():
    os.makedirs(os.path.dirname(SECRET_PATH), exist_ok=True)
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_PATH, encoding="utf-8") as f:
        return f.read().strip()


def create_app():
    app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
    app.secret_key = _ensure_secret()
    # max_upload_mb <= 0：不限制上传大小（主数据大表导入）
    max_mb = APP_CONFIG.get("server", {}).get("max_upload_mb", 0)
    try:
        max_mb = float(max_mb)
    except (TypeError, ValueError):
        max_mb = 0
    app.config["MAX_CONTENT_LENGTH"] = None if max_mb <= 0 else int(max_mb * 1024 * 1024)
    register_db(app)
    register_routes(app)

    @app.errorhandler(413)
    def _request_entity_too_large(_err):
        from flask import jsonify
        limit = APP_CONFIG.get("server", {}).get("max_upload_mb", 0)
        if not limit or float(limit) <= 0:
            msg = "上传被拒绝（请求体过大）。请检查反向代理或系统限制。"
        else:
            msg = (f"上传文件过大，单次请求上限 {limit}MB。"
                   f"可将 config/app_config.json 中 server.max_upload_mb 设为 0 取消限制后重启")
        return jsonify({"error": msg, "code": "payload_too_large"}), 413

    return app
