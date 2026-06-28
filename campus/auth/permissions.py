# -*- coding: utf-8 -*-
"""权限判定（纯分组授权模型，已取消业务角色）。

系统仅区分「系统管理员」(role=='admin') 与普通用户。普通用户的所有访问
能力由其所属权限分组及 ACL 矩阵决定，参见 campus.services.acl。
"""

# 兼容旧导入：保留 VALID_ROLES/GLOBAL_VIEW_ROLES 名字，但内容已收敛
VALID_ROLES = ("admin", "user")
GLOBAL_VIEW_ROLES = ("admin",)


def is_admin(user):
    return bool(user and user.get("role") == "admin")


def can_edit(user, group_id=None):
    """是否可编辑候选人：admin 或对所在数据分组具备 write 权限。
    仅做角色快速判定；精确判定请用 services.acl.can_edit_candidate。"""
    return is_admin(user)


def can_delete(user, group_id=None):
    return is_admin(user)


def can_view(user, group_id=None):
    return user is not None


# 兼容旧调用名
def can_edit_group(user, group_id=None):
    return is_admin(user)


def can_delete_group(user, group_id=None):
    return is_admin(user)


def can_view_group(user, group_id=None):
    return user is not None
