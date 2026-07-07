# -*- coding: utf-8 -*-
"""L4 接口层：Flask Blueprint（HTTP 参数解析、权限门禁、JSON 组装）。

约定：本层不写业务 SQL，数据操作调用 campus.services；纯规则调用
campus.domain；配置读取调用 campus.core。
"""
from campus.web.acl import bp as acl_bp
from campus.web.auth import bp as auth_bp
from campus.web.backups import bp as backups_bp
from campus.web.candidates import bp as candidates_bp
from campus.web.config import bp as config_bp
from campus.web.feedback import bp as feedback_bp
from campus.web.import_export import bp as import_export_bp
from campus.web.interviews import bp as interviews_bp
from campus.web.logs import bp as logs_bp
from campus.web.overview import bp as overview_bp
from campus.web.pages import bp as pages_bp
from campus.web.resumes import bp as resumes_bp
from campus.web.roles import bp as roles_bp
from campus.web.users import bp as users_bp


def register_routes(app):
    for bp in (
        auth_bp,
        config_bp,
        users_bp,
        roles_bp,
        candidates_bp,
        resumes_bp,
        import_export_bp,
        interviews_bp,
        logs_bp,
        overview_bp,
        backups_bp,
        pages_bp,
        acl_bp,
        feedback_bp,
    ):
        app.register_blueprint(bp)
