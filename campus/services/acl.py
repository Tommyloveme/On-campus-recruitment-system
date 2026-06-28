# -*- coding: utf-8 -*-
"""访问控制列表（ACL）权限解析引擎。

权限模型：
- 主体（subject）：用户 / 用户分组（user_group）。用户分组支持父子嵌套，
  父分组的权限可继承给子分组（由 permissions.inherit_user_group 控制）。
- 资源（resource）：当前为「数据分组」(groups 表，候选人的逻辑分区)。
  资源分组同样支持父子嵌套与继承（permissions.inherit_resource_group）。
- 权限维度：visibility / read / write / manage，均为 0/1 整数。
- 合并规则：用户同时属于多个用户分组时，按 permissions.merge_mode 取并集(union)
  或交集(intersect)；用户直接授予的权限始终与最终结果取并集（直接授权不会
  被交集规则削弱）。
- 特权：admin 受 permissions.admin_bypass 控制是否跳过 ACL；global_viewer 受
  permissions.global_viewer_sees_all 控制是否全局可见（只读）。
- 缓存：解析结果按请求缓存于 g._acl_cache，避免大规模场景下重复查询。
"""
from flask import g

from campus.settings import load_app_config

PERM_KEYS = ("visibility", "read", "write", "manage")
RESOURCE_TYPE_GROUP = "group"
SUBJECT_TYPE_USER = "user"
SUBJECT_TYPE_USER_GROUP = "user_group"


def permission_settings():
    cfg = load_app_config().get("permissions", {})
    return {
        "merge_mode": cfg.get("merge_mode", "union"),
        "inherit_user_group": bool(cfg.get("inherit_user_group", True)),
        "inherit_resource_group": bool(cfg.get("inherit_resource_group", True)),
        "admin_bypass": bool(cfg.get("admin_bypass", True)),
        "global_viewer_sees_all": bool(cfg.get("global_viewer_sees_all", True)),
        "unassigned_fallback_to_role": bool(cfg.get("unassigned_fallback_to_role", True)),
    }


def _empty_perms():
    return {k: 0 for k in PERM_KEYS}


def _full_perms():
    return {k: 1 for k in PERM_KEYS}


def _cache():
    if "_acl_cache" not in g:
        g._acl_cache = {}
    return g._acl_cache


# ---- 分组链路（向上取祖先，含自身） -----------------------------------------

def _ancestor_chain(db, table, id_col, parent_col, node_id):
    """返回从自身到根的 id 列表（含自身），防御环引用。"""
    chain = []
    seen = set()
    cur = node_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        row = db.execute(f"SELECT {parent_col} AS p FROM {table} WHERE {id_col}=?", (cur,)).fetchone()
        cur = row["p"] if row else None
    return chain


def user_group_chain(db, ug_id, settings=None):
    """用户分组继承链：自身 + 所有祖先分组（用于父组权限继承给子组）。"""
    settings = settings or permission_settings()
    chain = _ancestor_chain(db, "user_groups", "id", "parent_id", ug_id)
    if not settings["inherit_user_group"]:
        return [ug_id] if ug_id is not None else []
    return chain


def resource_group_chain(db, group_id, settings=None):
    """资源分组继承链：自身 + 所有祖先分组（用于父资源权限继承给子资源）。"""
    settings = settings or permission_settings()
    chain = _ancestor_chain(db, "groups", "id", "parent_id", group_id)
    if not settings["inherit_resource_group"]:
        return [group_id] if group_id is not None else []
    return chain


def user_group_ids_of(db, user_id):
    """用户直接所属的用户分组 id 列表。"""
    rows = db.execute(
        "SELECT group_id FROM user_group_members WHERE user_id=?", (user_id,)
    ).fetchall()
    return [r["group_id"] for r in rows]


# ---- 主体作用域展开 ---------------------------------------------------------

def _subject_scopes(db, user, settings):
    """返回主体作用域列表：[(subject_type, subject_id), ...]。

    用户直接授权 + 用户所在用户分组（按继承链展开到祖先分组）。
    """
    scopes = [(SUBJECT_TYPE_USER, user["id"])]
    for ug_id in user_group_ids_of(db, user["id"]):
        for aid in user_group_chain(db, ug_id, settings):
            scopes.append((SUBJECT_TYPE_USER_GROUP, aid))
    return scopes


# ---- 单主体权限合并 ---------------------------------------------------------

def _merge_rows(rows):
    """对一组 acl 行按位取或（同一主体在资源继承链上的多行取并集）。"""
    perms = _empty_perms()
    for r in rows:
        for k in PERM_KEYS:
            perms[k] |= int(r[f"perm_{k}"])
    return perms


def _combine_subject_perms(per_subject_list, merge_mode):
    """跨主体合并：union=或；intersect=与。"""
    if not per_subject_list:
        return _empty_perms()
    if merge_mode == "intersect":
        out = _full_perms()
        for p in per_subject_list:
            for k in PERM_KEYS:
                out[k] &= p[k]
        return out
    out = _empty_perms()
    for p in per_subject_list:
        for k in PERM_KEYS:
            out[k] |= p[k]
    return out


# ---- 核心：单资源权限解析 ---------------------------------------------------

def effective_permissions(db, user, resource_type, resource_id):
    """计算用户对指定资源的有效权限（带请求级缓存）。"""
    if user is None:
        return _empty_perms()
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return _full_perms()
    if st["global_viewer_sees_all"] and user["role"] == "global_viewer" and resource_type == RESOURCE_TYPE_GROUP:
        # 全局查看员对所有资源可见且只读
        return {"visibility": 1, "read": 1, "write": 0, "manage": 0}

    cache = _cache()
    key = (resource_type, resource_id)
    if key in cache:
        return cache[key]

    scopes = _subject_scopes(db, user, st)
    res_chain = resource_group_chain(db, resource_id, st) if resource_type == RESOURCE_TYPE_GROUP else [resource_id]
    if not res_chain:
        res_chain = [resource_id]
    res_ph = ",".join("?" * len(res_chain))

    # 用户直接授权：单独合并（始终 OR 进最终结果，不被交集削弱）
    direct_rows = db.execute(
        f"SELECT * FROM acl WHERE subject_type=? AND subject_id=? "
        f"AND resource_type=? AND resource_id IN ({res_ph})",
        [SUBJECT_TYPE_USER, user["id"], resource_type, *res_chain],
    ).fetchall()
    direct = _merge_rows(direct_rows)

    # 各用户分组分别计算（每组在资源继承链上取并集）
    ug_ids = []
    for s_type, s_id in scopes:
        if s_type == SUBJECT_TYPE_USER_GROUP:
            ug_ids.append(s_id)
    # 去重但保留顺序
    seen_ug = set()
    per_group = []
    for ug_id in ug_ids:
        if ug_id in seen_ug:
            continue
        seen_ug.add(ug_id)
        rows = db.execute(
            f"SELECT * FROM acl WHERE subject_type=? AND subject_id=? "
            f"AND resource_type=? AND resource_id IN ({res_ph})",
            [SUBJECT_TYPE_USER_GROUP, ug_id, resource_type, *res_chain],
        ).fetchall()
        per_group.append(_merge_rows(rows))

    combined = _combine_subject_perms(per_group, st["merge_mode"])
    final = _empty_perms()
    for k in PERM_KEYS:
        final[k] = direct[k] | combined[k]
    cache[key] = final
    return final


def can(db, user, resource_type, resource_id, perm):
    eff = effective_permissions(db, user, resource_type, resource_id)
    return bool(eff.get(perm))


# ---- 可见资源集合（用于列表过滤） -------------------------------------------

def accessible_resource_ids(db, user, resource_type=RESOURCE_TYPE_GROUP, perm="visibility"):
    """返回用户对指定资源类型具备 perm 权限的资源 id 集合。

    admin / global_viewer 返回 None 表示"全部可见"（调用方据此跳过过滤）。
    """
    if user is None:
        return set()
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return None
    if st["global_viewer_sees_all"] and user["role"] == "global_viewer" and resource_type == RESOURCE_TYPE_GROUP:
        return None

    # 列出所有资源，逐一判定（资源数量有限，可接受）
    if resource_type == RESOURCE_TYPE_GROUP:
        rows = db.execute("SELECT id FROM groups").fetchall()
    else:
        rows = []
    out = set()
    for r in rows:
        eff = effective_permissions(db, user, resource_type, r["id"])
        if eff.get(perm):
            out.add(r["id"])
    return out


# ---- 候选人可见性辅助 -------------------------------------------------------

def can_see_candidate(db, user, candidate_row):
    """候选人可见性判定：未分组走角色回退；已分组走 ACL。"""
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        if st["unassigned_fallback_to_role"]:
            # 沿用原有角色模型：登录用户均可见全部未分组候选人
            return True
        return False
    return can(db, user, RESOURCE_TYPE_GROUP, gid, "visibility")


def can_edit_candidate(db, user, candidate_row):
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        if st["unassigned_fallback_to_role"]:
            from campus.auth.permissions import can_edit_group
            return bool(can_edit_group(user))
        return False
    if user["role"] == "global_viewer":
        return False
    return can(db, user, RESOURCE_TYPE_GROUP, gid, "write")


def can_delete_candidate(db, user, candidate_row):
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        if st["unassigned_fallback_to_role"]:
            from campus.auth.permissions import can_delete_group
            return bool(can_delete_group(user))
        return False
    if user["role"] == "global_viewer":
        return False
    # 删除需要 write 权限（或 manage）
    return can(db, user, RESOURCE_TYPE_GROUP, gid, "write") or can(db, user, RESOURCE_TYPE_GROUP, gid, "manage")


# ---- ACL 行序列化 -----------------------------------------------------------

def acl_row_dict(r):
    return {
        "id": r["id"],
        "subject_type": r["subject_type"],
        "subject_id": r["subject_id"],
        "resource_type": r["resource_type"],
        "resource_id": r["resource_id"],
        "perm_visibility": int(r["perm_visibility"]),
        "perm_read": int(r["perm_read"]),
        "perm_write": int(r["perm_write"]),
        "perm_manage": int(r["perm_manage"]),
        "created_at": r["created_at"],
    }
