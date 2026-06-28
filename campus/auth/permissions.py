# -*- coding: utf-8 -*-
"""权限判定（纯模块授权模型，已取消业务角色与用户/资源分组）。

系统区分「系统管理员」(role=='admin' 或角色 bypass=true) 与普通用户。
普通用户的所有访问能力由其模块 ACL 矩阵决定，参见 campus.services.acl。
角色定义见 config/roles.json（campus.services.roles）。
"""

VALID_ROLES = ("admin", "user")
GLOBAL_VIEW_ROLES = ("admin",)


def is_admin(user):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    from campus.services.roles import role_bypass
    return role_bypass(user.get("role"))


def can_edit(user, group_id=None):
    """是否可编辑候选人：admin 直通；其余由端点的模块写门禁把关。"""
    return is_admin(user)


def can_delete(user, group_id=None):
    return is_admin(user)


def can_view(user, group_id=None):
    return user is not None
