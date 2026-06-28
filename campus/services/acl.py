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

from campus.db.connection import get_db
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


# ============================================================================
# 模块级 ACL：主界面板块/模块的可见性、可读性、可写性、管理权限
# ============================================================================
# 模块注册表：单一数据源，后端校验与前端导航渲染共用。
# 每个条目：{key, label, type(section|item), parent_key, role_gate}
#   - role_gate: 基线角色门禁（与 main.js buildNavStructure 保持一致），
#     在模块未启用 ACL 时生效；启用 ACL 后需同时满足 role_gate 与显式授权。
#     取值：None=任意已登录用户；或角色集合，如 {"admin","global_viewer"}。
MODULE_REGISTRY = [
    {"key": "registration", "label": "候选人登记", "type": "item", "parent_key": None, "role_gate": None},
    {"key": "recruit_flow", "label": "校招流程", "type": "section", "parent_key": None, "role_gate": None, "items": [
        {"key": "resume_screening", "label": "简历筛选", "type": "item", "parent_key": "recruit_flow", "role_gate": None},
        {"key": "qualification", "label": "资格审查", "type": "item", "parent_key": "recruit_flow", "role_gate": None},
        {"key": "written_test", "label": "笔试", "type": "item", "parent_key": "recruit_flow", "role_gate": None},
        {"key": "tech_interview", "label": "技术面", "type": "item", "parent_key": "recruit_flow", "role_gate": None},
        {"key": "manager_interview", "label": "主管面", "type": "item", "parent_key": "recruit_flow", "role_gate": None},
    ]},
    {"key": "offer_strategy", "label": "Offer策略", "type": "section", "parent_key": None, "role_gate": None, "items": [
        {"key": "approval", "label": "报批", "type": "item", "parent_key": "offer_strategy", "role_gate": None},
        {"key": "salary", "label": "谈薪", "type": "item", "parent_key": "offer_strategy", "role_gate": None},
        {"key": "offer", "label": "Offer管理", "type": "item", "parent_key": "offer_strategy", "role_gate": None},
    ]},
    {"key": "onboarding", "label": "入职管理", "type": "item", "parent_key": None, "role_gate": None},
    {"key": "data_board", "label": "数据看板", "type": "section", "parent_key": None,
     "role_gate": ("admin", "global_viewer", "group_admin"), "items": [
        {"key": "overview", "label": "全局总览", "type": "item", "parent_key": "data_board",
         "role_gate": ("admin", "global_viewer")},
        {"key": "charts", "label": "数据图表", "type": "item", "parent_key": "data_board",
         "role_gate": ("admin", "group_admin")},
    ]},
    {"key": "admin_board", "label": "管理看板", "type": "section", "parent_key": None,
     "role_gate": ("admin",), "items": [
        {"key": "logs", "label": "操作日志", "type": "item", "parent_key": "admin_board", "role_gate": ("admin",)},
        {"key": "admin", "label": "系统管理", "type": "item", "parent_key": "admin_board", "role_gate": ("admin",)},
        {"key": "permissions", "label": "权限管理", "type": "item", "parent_key": "admin_board", "role_gate": ("admin",)},
    ]},
]

# 扁平化：module_key -> 条目（含 parent_key 链）
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
    """所有模块 key（含 section 与 item）。"""
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


def module_acl_enabled(db, module_key):
    """模块是否启用了 ACL 门禁。未启用时走 role_gate 基线。"""
    row = db.execute(
        "SELECT enabled FROM module_acl_meta WHERE module_key=?", (module_key,)
    ).fetchone()
    return bool(row and row["enabled"])


def set_module_acl_enabled(db, module_key, enabled):
    db.execute(
        "INSERT INTO module_acl_meta (module_key, enabled) VALUES (?,?) "
        "ON CONFLICT(module_key) DO UPDATE SET enabled=excluded.enabled",
        (module_key, 1 if enabled else 0),
    )


def module_role_gate_passed(user, module_key):
    """基线角色门禁（未启用 ACL 时使用）。"""
    entry = _MODULE_INDEX.get(module_key)
    if not entry:
        return False
    gate = entry.get("role_gate")
    if gate is None:
        return True  # 任意已登录用户
    return user["role"] in gate


def effective_module_perms(db, user, module_key):
    """计算用户对某模块的有效权限。

    返回 dict {visibility, read, write, manage}；若模块未启用 ACL 门禁，
    返回 None（调用方应回退到 role_gate 基线）。
    admin（admin_bypass=True）始终返回全权。
    """
    if user is None:
        return None
    st = permission_settings()
    if st["admin_bypass"] and user["role"] == "admin":
        return {"visibility": 1, "read": 1, "write": 1, "manage": 1}

    if not module_acl_enabled(db, module_key):
        return None  # 未启用 → 走 role_gate 基线

    cache = _cache()
    mkey = ("module", module_key)
    if mkey in cache:
        return cache[mkey]

    scopes = _subject_scopes(db, user, st)
    chain = module_ancestor_chain(module_key)
    if not chain:
        chain = [module_key]
    key_ph = ",".join("?" * len(chain))

    direct_rows = db.execute(
        f"SELECT * FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key IN ({key_ph})",
        [SUBJECT_TYPE_USER, user["id"], *chain],
    ).fetchall()
    direct = _merge_module_rows(direct_rows)

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
    """模块是否对用户可见（综合 role_gate 与 ACL）。"""
    if user is None:
        return False
    db = get_db()
    eff = effective_module_perms(db, user, module_key)
    if eff is None:
        return module_role_gate_passed(user, module_key)
    return bool(eff["visibility"])


def module_readable_for(user, module_key):
    if user is None:
        return False
    db = get_db()
    eff = effective_module_perms(db, user, module_key)
    if eff is None:
        return module_role_gate_passed(user, module_key)
    return bool(eff["read"])


def module_writable_for(user, module_key):
    if user is None:
        return False
    db = get_db()
    eff = effective_module_perms(db, user, module_key)
    if eff is None:
        # 未启用 ACL：写权限沿用既有角色模型（editor/group_admin/admin 可写）
        return user["role"] in ("admin", "group_admin", "editor")
    return bool(eff["write"])


def module_endpoint_read_ok(user, module_key):
    """端点级读校验：模块未启用 ACL 时返回 True（不增加限制，沿用端点既有角色逻辑）；
    启用后要求有效 read 权限。供 /api/overview、/api/logs 等内容端点使用。"""
    if user is None:
        return False
    db = get_db()
    if not module_acl_enabled(db, module_key):
        return True
    eff = effective_module_perms(db, user, module_key)
    return bool(eff and eff["read"])


def module_endpoint_write_ok(user, module_key):
    """端点级写校验：未启用时返回 True；启用后要求有效 write 权限。"""
    if user is None:
        return False
    db = get_db()
    if not module_acl_enabled(db, module_key):
        return True
    eff = effective_module_perms(db, user, module_key)
    return bool(eff and eff["write"])


def module_registry_payload(user=None):
    """模块注册表 + 每个模块的启用状态与当前用户的有效权限（供前端导航）。"""
    db = get_db()
    out = []
    for entry in MODULE_REGISTRY:
        e = {"key": entry["key"], "label": entry["label"], "type": entry["type"],
             "role_gate": list(entry["role_gate"]) if entry.get("role_gate") else None,
             "enabled": module_acl_enabled(db, entry["key"])}
        if user is not None:
            eff = effective_module_perms(db, user, entry["key"])
            e["effective"] = eff
            e["visible"] = module_visible_for(user, entry["key"])
            e["readable"] = module_readable_for(user, entry["key"])
            e["writable"] = module_writable_for(user, entry["key"])
        if "items" in entry:
            e["items"] = []
            for child in entry["items"]:
                ci = {"key": child["key"], "label": child["label"], "type": child["type"],
                      "role_gate": list(child["role_gate"]) if child.get("role_gate") else None,
                      "enabled": module_acl_enabled(db, child["key"])}
                if user is not None:
                    eff = effective_module_perms(db, user, child["key"])
                    ci["effective"] = eff
                    ci["visible"] = module_visible_for(user, child["key"])
                    ci["readable"] = module_readable_for(user, child["key"])
                    ci["writable"] = module_writable_for(user, child["key"])
                e["items"].append(ci)
        out.append(e)
    return out
