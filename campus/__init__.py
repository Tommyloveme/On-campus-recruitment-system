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
    app.config["MAX_CONTENT_LENGTH"] = APP_CONFIG["server"]["max_upload_mb"] * 1024 * 1024
    register_db(app)
    register_routes(app)
    return app
