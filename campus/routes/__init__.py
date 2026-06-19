# -*- coding: utf-8 -*-
"""注册所有 Blueprint 路由。"""
from campus.routes.auth import bp as auth_bp
from campus.routes.backups import bp as backups_bp
from campus.routes.candidates import bp as candidates_bp
from campus.routes.config import bp as config_bp
from campus.routes.groups import bp as groups_bp
from campus.routes.import_export import bp as import_export_bp
from campus.routes.interviews import bp as interviews_bp
from campus.routes.logs import bp as logs_bp
from campus.routes.overview import bp as overview_bp
from campus.routes.pages import bp as pages_bp
from campus.routes.resumes import bp as resumes_bp
from campus.routes.users import bp as users_bp


def register_routes(app):
    for bp in (
        auth_bp,
        config_bp,
        groups_bp,
        users_bp,
        candidates_bp,
        resumes_bp,
        import_export_bp,
        interviews_bp,
        logs_bp,
        overview_bp,
        backups_bp,
        pages_bp,
    ):
        app.register_blueprint(bp)
