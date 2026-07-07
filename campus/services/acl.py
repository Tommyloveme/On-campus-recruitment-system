# -*- coding: utf-8 -*-
"""访问控制（ACL）权限解析引擎（纯模块授权模型）。

权限模型：
- 唯一性由工号(username)决定；其余均为附属信息（见 config/user_fields.json）。
- 候选人数据为单一共享池（已取消资源分组），所有登录用户可见；
  编辑/删除由「模块写权限」按候选人当前所处阶段模块门禁。
- 模块权限：每条 module_acl 为 用户(工号) × 模块 的 visibility/read/write/manage
  四个独立标志；板块权限向其下子模块继承。模块清单见 campus.core.modules。
- 管理员判定：`is_admin()` 是全系统唯一实现——role=='admin' 或该角色在
  config/roles.json 中标记 bypass=true，均视为系统管理员直通。
- 缓存：解析结果按请求缓存于 g._acl_cache。
"""
import json

from flask import g

from campus.core.modules import (  # noqa: F401  （对外统一从本模块取用）
    MODULE_REGISTRY,
    module_ancestor_chain,
    module_entry,
    module_keys,
)
from campus.core.roles_store import role_bypass
from campus.core.settings import load_app_config
from campus.db.connection import get_db

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
    """系统管理员判定（唯一实现）：role=='admin' 或角色 bypass=true。"""
    if not user:
        return False
    try:
        role = user["role"]
    except (TypeError, KeyError, IndexError):
        role = getattr(user, "get", lambda _k, _d=None: None)("role")
    if role == "admin":
        return True
    return role_bypass(role)


# ---- 候选人共享池可见性 / 编辑 / 删除 -------------------------------------

def _candidate_current_stage(row):
    try:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        return (data or {}).get("current_stage")
    except (TypeError, json.JSONDecodeError):
        return None


def can_see_candidate(db, user, candidate_row):
    """共享池：所有登录用户可见。"""
    return user is not None


def can_edit_candidate(db, user, candidate_row):
    """共享池编辑：由端点的模块写门禁把关（阶段即模块 key），此处仅要求登录。"""
    return user is not None


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
# 模块级 ACL 解析：用户(工号) × 模块 的 visibility/read/write/manage
# ============================================================================

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
    # 问题反馈：全员可见（登录即可在侧栏进入）
    if module_key == "feedback":
        return True
    return bool(effective_module_perms(get_db(), user, module_key)["visibility"])


def module_readable_for(user, module_key):
    if user is None:
        return False
    if module_key == "feedback":
        return True
    return bool(effective_module_perms(get_db(), user, module_key)["read"])


def module_writable_for(user, module_key):
    if user is None:
        return False
    return bool(effective_module_perms(get_db(), user, module_key)["write"])


def module_registry_payload(user=None):
    """模块注册表 + 当前用户对各模块的有效权限（供前端导航渲染）。"""
    db = get_db()
    out = []
    for entry in MODULE_REGISTRY:
        e = {"key": entry["key"], "label": entry["label"], "type": entry["type"]}
        if user is not None:
            eff = effective_module_perms(db, user, entry["key"])
            e["effective"] = eff
            e["visible"] = module_visible_for(user, entry["key"])
            e["readable"] = module_readable_for(user, entry["key"])
            e["writable"] = bool(eff["write"])
        if "items" in entry:
            e["items"] = []
            for child in entry["items"]:
                ci = {"key": child["key"], "label": child["label"], "type": child["type"]}
                if user is not None:
                    eff = effective_module_perms(db, user, child["key"])
                    ci["effective"] = eff
                    ci["visible"] = module_visible_for(user, child["key"])
                    ci["readable"] = module_readable_for(user, child["key"])
                    ci["writable"] = bool(eff["write"])
                e["items"].append(ci)
        out.append(e)
    return out


# ============================================================================
# 模块 ACL 存取（供 web 层权限管理接口调用，SQL 收敛于此）
# ============================================================================

def query_module_acl(db, module_key=None, subject_id=None):
    sql = "SELECT * FROM module_acl WHERE subject_type=?"
    args = [SUBJECT_TYPE_USER]
    if module_key:
        sql += " AND module_key=?"
        args.append(module_key)
    if subject_id is not None:
        sql += " AND subject_id=?"
        args.append(subject_id)
    sql += " ORDER BY module_key, subject_id"
    return db.execute(sql, args).fetchall()


def upsert_module_acl(db, subject_id, module_key, perms):
    """perms: {perm_visibility, perm_read, perm_write, perm_manage} 均为 0/1。"""
    from campus.db.connection import now_str
    existing = db.execute(
        "SELECT id FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
        (SUBJECT_TYPE_USER, subject_id, module_key),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE module_acl SET perm_visibility=?, perm_read=?, perm_write=?, perm_manage=? WHERE id=?",
            (perms["perm_visibility"], perms["perm_read"], perms["perm_write"], perms["perm_manage"], existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO module_acl (subject_type, subject_id, module_key, "
            "perm_visibility, perm_read, perm_write, perm_manage, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (SUBJECT_TYPE_USER, subject_id, module_key, perms["perm_visibility"], perms["perm_read"],
             perms["perm_write"], perms["perm_manage"], now_str()),
        )


def delete_module_acl(db, subject_id, module_key):
    db.execute(
        "DELETE FROM module_acl WHERE subject_type=? AND subject_id=? AND module_key=?",
        (SUBJECT_TYPE_USER, subject_id, module_key),
    )
