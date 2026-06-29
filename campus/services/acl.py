# -*- coding: utf-8 -*-
"""访问控制列表（ACL）权限解析引擎（纯模块授权模型）。

权限模型：
- 唯一性由工号(username)决定；其余均为附属信息（见 config/user_fields.json）。
- 候选人数据为单一共享池（已取消资源分组），所有登录用户可见；
  编辑/删除由「模块写权限」按候选人当前所处阶段模块门禁。
- 模块权限：每条 module_acl 为 用户(工号) × 模块 的 visibility/read/write/manage
  四个独立标志；板块权限向其下子模块继承。系统管理员(admin)受 admin_bypass 直通。
- 缓存：解析结果按请求缓存于 g._acl_cache。
"""
import json

from flask import g

from campus.db.connection import get_db
from campus.settings import load_app_config

PERM_KEYS = ("visibility", "read", "write", "manage")
SUBJECT_TYPE_USER = "user"


def permission_settings():
    cfg = load_app_config().get("permissions", {})
    return {
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


# ---- 候选人共享池可见性 / 编辑 / 删除 -------------------------------------

def _candidate_current_stage(row):
    try:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        return (data or {}).get("current_stage")
    except (TypeError, json.JSONDecodeError):
        return None


def can_see_candidate(db, user, candidate_row):
    """共享池：所有登录用户可见；admin 直通。"""
    if user is None:
        return False
    return True


def can_edit_candidate(db, user, candidate_row):
    """共享池编辑：admin 直通；其余由端点的模块写门禁把关（阶段即模块 key）。"""
    if user is None:
        return False
    return True


def can_delete_candidate(db, user, candidate_row):
    """删除：admin 直通；其余需对候选人当前阶段模块具备写权限。"""
    if user is None:
        return False
    if is_admin(user):
        return True
    stage = _candidate_current_stage(candidate_row)
    if not stage:
        return False
    return module_writable_for(user, stage)


# ============================================================================
# 模块级 ACL：用户(工号) × 模块 的 visibility/read/write/manage
# ============================================================================
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
    {"key": "feedback", "label": "问题反馈", "type": "item", "parent_key": None},
    {"key": "data_board", "label": "数据看板", "type": "section", "parent_key": None, "items": [
        {"key": "overview", "label": "全局总览", "type": "item", "parent_key": "data_board"},
        {"key": "charts", "label": "数据图表", "type": "item", "parent_key": "data_board"},
    ]},
    {"key": "admin_board", "label": "管理看板", "type": "section", "parent_key": None, "items": [
        {"key": "permissions", "label": "权限管理", "type": "item", "parent_key": "admin_board"},
        {"key": "op_logs", "label": "操作日志", "type": "item", "parent_key": "admin_board"},
        {"key": "backups", "label": "数据备份", "type": "item", "parent_key": "admin_board"},
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
    """模块继承链：自身 → 所属板块 → ...（板块权限下发给子模块）。"""
    chain = []
    seen = set()
    cur = module_key
    while cur and cur in _MODULE_INDEX and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _MODULE_INDEX[cur].get("parent_key")
    return chain


def _merge_module_rows(rows):
    perms = _empty_perms()
    for r in rows:
        for k in PERM_KEYS:
            perms[k] |= int(r[f"perm_{k}"])
    return perms


def effective_module_perms(db, user, module_key):
    """用户对模块的有效权限：用户直接授权（含板块→子模块继承）；admin 直通全权。"""
    if user is None:
        return _empty_perms()
    if permission_settings()["admin_bypass"] and is_admin(user):
        return _full_perms()

    cache = _cache()
    mkey = ("module", module_key)
    if mkey in cache:
        return cache[mkey]

    chain = module_ancestor_chain(module_key) or [module_key]
    key_ph = ",".join("?" * len(chain))
    rows = db.execute(
        f"SELECT * FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key IN ({key_ph})",
        [SUBJECT_TYPE_USER, user["id"], *chain],
    ).fetchall()
    final = _merge_module_rows(rows)
    cache[mkey] = final
    return final


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
    return bool(effective_module_perms(get_db(), user, module_key)["visibility"])


def module_readable_for(user, module_key):
    if user is None:
        return False
    return bool(effective_module_perms(get_db(), user, module_key)["read"])


def module_writable_for(user, module_key):
    if user is None:
        return False
    return bool(effective_module_perms(get_db(), user, module_key)["write"])


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
