# -*- coding: utf-8 -*-
"""访问控制列表（ACL）权限解析引擎。

权限模型（纯分组授权，已取消业务角色）：
- 主体（subject）：用户 / 用户分组（user_group）。用户分组支持父子嵌套，
  父分组的权限可继承给子分组（由 permissions.inherit_user_group 控制）。
- 资源（resource）：「数据分组」(groups 表，候选人的逻辑分区) 与「模块」
  (主界面板块/子模块，module_acl 表)。
- 权限维度：visibility / read / write / manage，均为 0/1 整数。
- 合并规则：用户同时属于多个用户分组时，按 permissions.merge_mode 取并集(union)
  或交集(intersection)；用户直接授予的权限始终与最终结果取并集（直接授权不会
  被交集规则削弱）。
- 特权：仅系统管理员（role=='admin'）受 permissions.admin_bypass 控制是否跳过 ACL。
- 默认分组：新建用户自动加入「默认分组」，其基线权限由管理员配置。
- 缓存：解析结果按请求缓存于 g._acl_cache，避免大规模场景下重复查询。
"""
from flask import g

from campus.db.connection import get_db, now_str
from campus.settings import load_app_config

PERM_KEYS = ("visibility", "read", "write", "manage")
RESOURCE_TYPE_GROUP = "group"
SUBJECT_TYPE_USER = "user"
SUBJECT_TYPE_USER_GROUP = "user_group"

DEFAULT_GROUP_NAME = "默认分组"


def permission_settings():
    cfg = load_app_config().get("permissions", {})
    return {
        "merge_mode": cfg.get("merge_mode", "union"),
        "inherit_user_group": bool(cfg.get("inherit_user_group", True)),
        "inherit_resource_group": bool(cfg.get("inherit_resource_group", True)),
        "admin_bypass": bool(cfg.get("admin_bypass", True)),
    }


def _empty_perms():
    return {k: 0 for k in PERM_KEYS}


def _full_perms():
    return {k: 1 for k in PERM_KEYS}


def _cache():
    if "_acl_cache" not in g:
        g._acl_cache = {}
    return g._acl_cache


def is_admin(user):
    return bool(user and user["role"] == "admin")


# ---- 默认分组 -------------------------------------------------------------

def ensure_default_group(db):
    """确保「默认分组」存在，返回其 row。"""
    row = db.execute("SELECT * FROM user_groups WHERE name=?", (DEFAULT_GROUP_NAME,)).fetchone()
    if row:
        return row
    db.execute(
        "INSERT INTO user_groups (name, description, parent_id, created_at) VALUES (?,?,?,?)",
        (DEFAULT_GROUP_NAME, "新建用户默认归属，基线权限由管理员配置", None, now_str()),
    )
    db.commit()
    return db.execute("SELECT * FROM user_groups WHERE name=?", (DEFAULT_GROUP_NAME,)).fetchone()


def default_group_id(db):
    return ensure_default_group(db)["id"]


def auto_join_default_group(db, user_id):
    """将用户加入默认分组（若尚未属于任何分组则加入；否则也加入以保证基线权限）。"""
    dg_id = default_group_id(db)
    existing = db.execute(
        "SELECT 1 FROM user_group_members WHERE group_id=? AND user_id=?", (dg_id, user_id)
    ).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO user_group_members (group_id, user_id, created_at) VALUES (?,?,?)",
            (dg_id, user_id, now_str()),
        )
        db.commit()


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


def descendant_user_group_ids(db, ug_id):
    """返回 ug_id 的全部子孙分组 id（含自身），用于"应用到子分组"。"""
    out = [ug_id]
    stack = [ug_id]
    while stack:
        cur = stack.pop()
        rows = db.execute(
            "SELECT id FROM user_groups WHERE parent_id=?", (cur,)
        ).fetchall()
        for r in rows:
            out.append(r["id"])
            stack.append(r["id"])
    return out


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
    """计算用户对指定数据资源的有效权限（带请求级缓存）。"""
    if user is None:
        return _empty_perms()
    st = permission_settings()
    if st["admin_bypass"] and is_admin(user):
        return _full_perms()

    cache = _cache()
    key = (resource_type, resource_id)
    if key in cache:
        return cache[key]

    scopes = _subject_scopes(db, user, st)
    res_chain = resource_group_chain(db, resource_id, st) if resource_type == RESOURCE_TYPE_GROUP else [resource_id]
    if not res_chain:
        res_chain = [resource_id]
    res_ph = ",".join("?" * len(res_chain))

    direct_rows = db.execute(
        f"SELECT * FROM acl WHERE subject_type=? AND subject_id=? "
        f"AND resource_type=? AND resource_id IN ({res_ph})",
        [SUBJECT_TYPE_USER, user["id"], resource_type, *res_chain],
    ).fetchall()
    direct = _merge_rows(direct_rows)

    ug_ids = []
    for s_type, s_id in scopes:
        if s_type == SUBJECT_TYPE_USER_GROUP:
            ug_ids.append(s_id)
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

    admin 返回 None 表示"全部可见"（调用方据此跳过过滤）。
    """
    if user is None:
        return set()
    st = permission_settings()
    if st["admin_bypass"] and is_admin(user):
        return None

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
    """候选人可见性：未分组候选人作为共享池对所有登录用户可见；已分组走 ACL。"""
    if user is None:
        return False
    if is_admin(user):
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        return True  # 共享池：未分配数据分组的候选人对所有登录用户可见
    return can(db, user, RESOURCE_TYPE_GROUP, gid, "visibility")


def can_edit_candidate(db, user, candidate_row):
    if user is None:
        return False
    if is_admin(user):
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        return True  # 共享池：未分配数据分组的候选人对所有登录用户可编辑
    return can(db, user, RESOURCE_TYPE_GROUP, gid, "write")


def can_delete_candidate(db, user, candidate_row):
    if user is None:
        return False
    if is_admin(user):
        return True
    gid = candidate_row["group_id"] if "group_id" in candidate_row.keys() else None
    if gid is None:
        return True  # 共享池：对所有登录用户可删除
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


# ============================================================================
# 模块级 ACL：主界面板块/模块的可见性、可读性、可写性、管理权限
# ============================================================================
# 模块注册表：单一数据源，后端校验与前端导航渲染共用。
# 每个条目：{key, label, type(section|item), parent_key}
# 模块恒为 ACL 门禁（无 role_gate 基线）；用户有效权限来自其所属分组的授权。
MODULE_REGISTRY = [
    {"key": "registration", "label": "候选人登记", "type": "item", "parent_key": None},
    {"key": "recruit_flow", "label": "校招流程", "type": "section", "parent_key": None, "items": [
        {"key": "resume_screening", "label": "简历筛选", "type": "item", "parent_key": "recruit_flow"},
        {"key": "qualification", "label": "资格审查", "type": "item", "parent_key": "recruit_flow"},
        {"key": "written_test", "label": "笔试", "type": "item", "parent_key": "recruit_flow"},
        {"key": "tech_interview", "label": "技术面", "type": "item", "parent_key": "recruit_flow"},
        {"key": "manager_interview", "label": "主管面", "type": "item", "parent_key": "recruit_flow"},
    ]},
    {"key": "offer_strategy", "label": "Offer策略", "type": "section", "parent_key": None, "items": [
        {"key": "approval", "label": "报批", "type": "item", "parent_key": "offer_strategy"},
        {"key": "salary", "label": "谈薪", "type": "item", "parent_key": "offer_strategy"},
        {"key": "offer", "label": "Offer管理", "type": "item", "parent_key": "offer_strategy"},
    ]},
    {"key": "onboarding", "label": "入职管理", "type": "item", "parent_key": None},
    {"key": "data_board", "label": "数据看板", "type": "section", "parent_key": None, "items": [
        {"key": "overview", "label": "全局总览", "type": "item", "parent_key": "data_board"},
        {"key": "charts", "label": "数据图表", "type": "item", "parent_key": "data_board"},
    ]},
    {"key": "admin_board", "label": "管理看板", "type": "section", "parent_key": None, "items": [
        {"key": "logs", "label": "操作日志", "type": "item", "parent_key": "admin_board"},
        {"key": "admin", "label": "系统管理", "type": "item", "parent_key": "admin_board"},
        {"key": "permissions", "label": "权限管理", "type": "item", "parent_key": "admin_board"},
    ]},
]

_MODULE_INDEX = {}


def _build_module_index():
    _MODULE_INDEX.clear()
    def walk(entry, parent_key):
        e = {k: v for k, v in entry.items() if k != "items"}
        e["parent_key"] = parent_key
        _MODULE_INDEX[e["key"]] = e
        for child in entry.get("items", []):
            walk(child, e["key"])
    for entry in MODULE_REGISTRY:
        walk(entry, entry.get("parent_key"))


_build_module_index()


def module_keys():
    return list(_MODULE_INDEX.keys())


def module_entry(key):
    return _MODULE_INDEX.get(key)


def module_ancestor_chain(module_key):
    """模块继承链：自身 → 所属板块 → ...（用于板块权限下发给子模块）。"""
    chain = []
    seen = set()
    cur = module_key
    while cur and cur in _MODULE_INDEX and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _MODULE_INDEX[cur].get("parent_key")
    return chain


def effective_module_perms(db, user, module_key):
    """计算用户对某模块的有效权限。

    返回 dict {visibility, read, write, manage}。admin（admin_bypass）始终全权。
    模块恒为 ACL 门禁：权限来自用户直接授权 + 所属分组（含继承）授权。
    """
    if user is None:
        return _empty_perms()
    st = permission_settings()
    if st["admin_bypass"] and is_admin(user):
        return {"visibility": 1, "read": 1, "write": 1, "manage": 1}

    cache = _cache()
    mkey = ("module", module_key)
    if mkey in cache:
        return cache[mkey]

    scopes = _subject_scopes(db, user, st)
    chain = module_ancestor_chain(module_key) or [module_key]
    key_ph = ",".join("?" * len(chain))

    direct_rows = db.execute(
        f"SELECT * FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key IN ({key_ph})",
        [SUBJECT_TYPE_USER, user["id"], *chain],
    ).fetchall()
    direct = _merge_module_rows(direct_rows)

    ug_ids = [s_id for s_type, s_id in scopes if s_type == SUBJECT_TYPE_USER_GROUP]
    seen_ug = set()
    per_group = []
    for ug_id in ug_ids:
        if ug_id in seen_ug:
            continue
        seen_ug.add(ug_id)
        rows = db.execute(
            f"SELECT * FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key IN ({key_ph})",
            [SUBJECT_TYPE_USER_GROUP, ug_id, *chain],
        ).fetchall()
        per_group.append(_merge_module_rows(rows))

    combined = _combine_subject_perms(per_group, st["merge_mode"])
    final = {"visibility": 0, "read": 0, "write": 0, "manage": 0}
    for k in PERM_KEYS:
        final[k] = direct[k] | combined[k]
    cache[mkey] = final
    return final


def _merge_module_rows(rows):
    perms = _empty_perms()
    for r in rows:
        for k in PERM_KEYS:
            perms[k] |= int(r[f"perm_{k}"])
    return perms


def module_acl_row_dict(r):
    return {
        "id": r["id"],
        "subject_type": r["subject_type"],
        "subject_id": r["subject_id"],
        "module_key": r["module_key"],
        "perm_visibility": int(r["perm_visibility"]),
        "perm_read": int(r["perm_read"]),
        "perm_write": int(r["perm_write"]),
        "perm_manage": int(r["perm_manage"]),
        "created_at": r["created_at"],
    }


def module_visible_for(user, module_key):
    if user is None:
        return False
    db = get_db()
    return bool(effective_module_perms(db, user, module_key)["visibility"])


def module_readable_for(user, module_key):
    if user is None:
        return False
    db = get_db()
    return bool(effective_module_perms(db, user, module_key)["read"])


def module_writable_for(user, module_key):
    if user is None:
        return False
    db = get_db()
    return bool(effective_module_perms(db, user, module_key)["write"])


# 端点级校验别名（模块恒门禁，与 *_for 一致）
def module_endpoint_read_ok(user, module_key):
    return module_readable_for(user, module_key)


def module_endpoint_write_ok(user, module_key):
    return module_writable_for(user, module_key)


def module_registry_payload(user=None):
    """模块注册表 + 当前用户对各模块的有效权限（供前端导航渲染）。"""
    db = get_db()
    out = []
    for entry in MODULE_REGISTRY:
        e = {"key": entry["key"], "label": entry["label"], "type": entry["type"]}
        if user is not None:
            eff = effective_module_perms(db, user, entry["key"])
            e["effective"] = eff
            e["visible"] = bool(eff["visibility"])
            e["readable"] = bool(eff["read"])
            e["writable"] = bool(eff["write"])
        if "items" in entry:
            e["items"] = []
            for child in entry["items"]:
                ci = {"key": child["key"], "label": child["label"], "type": child["type"]}
                if user is not None:
                    eff = effective_module_perms(db, user, child["key"])
                    ci["effective"] = eff
                    ci["visible"] = bool(eff["visibility"])
                    ci["readable"] = bool(eff["read"])
                    ci["writable"] = bool(eff["write"])
                e["items"].append(ci)
        out.append(e)
    return out
