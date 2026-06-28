# -*- coding: utf-8 -*-
from campus.auth.decorators import admin_required, login_required
from campus.auth.permissions import GLOBAL_VIEW_ROLES, VALID_ROLES, can_view

__all__ = [
    "login_required",
    "admin_required",
    "VALID_ROLES",
    "GLOBAL_VIEW_ROLES",
    "can_view",
]
