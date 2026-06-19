# -*- coding: utf-8 -*-
"""角色权限判定（已移除分组维度）。"""

VALID_ROLES = ("admin", "global_viewer", "group_admin", "editor", "viewer")
GLOBAL_VIEW_ROLES = ("admin", "global_viewer")


def can_edit(user, group_id=None):
    return user["role"] in ("admin", "group_admin", "editor")


def can_delete(user, group_id=None):
    return user["role"] in ("admin", "group_admin")


def can_view(user, group_id=None):
    return user["role"] in GLOBAL_VIEW_ROLES or user["role"] in ("group_admin", "editor", "viewer")


# 兼容旧调用名
def can_edit_group(user, group_id=None):
    return can_edit(user)


def can_delete_group(user, group_id=None):
    return can_delete(user)


def can_view_group(user, group_id=None):
    return can_view(user)
