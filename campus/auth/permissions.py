# -*- coding: utf-8 -*-
"""权限判定（纯模块授权模型，已取消业务角色与用户/资源分组）。

系统仅区分「系统管理员」(role=='admin') 与普通用户。普通用户的所有访问
能力由其模块 ACL 矩阵决定，参见 campus.services.acl。
"""

VALID_ROLES = ("admin", "user")
GLOBAL_VIEW_ROLES = ("admin",)


def is_admin(user):
    return bool(user and user.get("role") == "admin")


def can_edit(user, group_id=None):
    """是否可编辑候选人：admin 直通；其余由端点的模块写门禁把关。"""
    return is_admin(user)


def can_delete(user, group_id=None):
    return is_admin(user)


def can_view(user, group_id=None):
    return user is not None
