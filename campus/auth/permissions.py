# -*- coding: utf-8 -*-
"""角色与分组权限判定。"""

VALID_ROLES = ("admin", "global_viewer", "group_admin", "editor", "viewer")
GLOBAL_VIEW_ROLES = ("admin", "global_viewer")


def can_edit_group(user, group_id):
    if user["role"] == "admin":
        return True
    return user["role"] in ("group_admin", "editor") and user["group_id"] == group_id


def can_delete_group(user, group_id):
    if user["role"] == "admin":
        return True
    return user["role"] == "group_admin" and user["group_id"] == group_id


def can_view_group(user, group_id):
    return user["role"] in GLOBAL_VIEW_ROLES or user["group_id"] == group_id
