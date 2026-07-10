# -*- coding: utf-8 -*-
"""校招系统后端包：create_app() 应用工厂（app.py 与测试共用的唯一入口）。

五层架构（依赖只允许自上而下，详见 docs/维测指导手册.md §1.2）：

    L4 campus/web       HTTP 接口层：Blueprint 路由 + guards 门禁装饰器
    L3 campus/services  业务服务层：acl / candidates / master_import / ...
    L2 campus/db        数据访问层：connection（WAL 连接）/ schema / field_store
    L1 campus/domain    领域规则层：stage_routing / rule_engine / interview_slots
    L0 campus/core      基础层：settings / modules / stage_config / net_util / ...

- 路由注册：campus/web/__init__.py register_routes()
- 数据库初始化（建表/迁移/演示数据）：campus/db/schema.py init_db()，由 app.py 调用
- 上传大小限制：config/app_config.json server.max_upload_mb（<=0 不限制）
"""
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
