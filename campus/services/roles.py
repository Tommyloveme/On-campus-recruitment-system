# -*- coding: utf-8 -*-
"""角色（权限模板）服务：加载/保存/CRUD，持久化到 config/roles.json。

角色 = 权限模板。每个角色定义 key/label/bypass/perms。
应用角色到用户时，将 perms 写入该用户的 module_acl（覆盖其原有模块权限）。
bypass=true 的角色绕过所有模块权限（系统管理员）。
"""
import json
import os

from campus.settings import ROLES_PATH

_cache = None


def _read():
    """从磁盘读取 roles.json（带内存缓存，写操作会刷新缓存）。"""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(ROLES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {"roles": []}
    _cache = data
    return _cache


def _flush(data):
    """写回 roles.json 并刷新缓存。"""
    global _cache
    os.makedirs(os.path.dirname(ROLES_PATH), exist_ok=True)
    with open(ROLES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache = data


def reload_roles():
    """清除缓存，下次读取重新加载。"""
    global _cache
    _cache = None


def all_roles():
    return list(_read().get("roles", []))


def role_keys():
    return [r["key"] for r in all_roles()]


def get_role(key):
    for r in all_roles():
        if r["key"] == key:
            return r
    return None


def role_label(key):
    r = get_role(key)
    return r["label"] if r else (key or "")


def role_bypass(key):
    r = get_role(key)
    return bool(r and r.get("bypass"))


def role_is_builtin(key):
    r = get_role(key)
    return bool(r and r.get("builtin"))


def role_perms(key):
    """返回角色的模块权限映射 {module_key: {v,r,w,m}}。"""
    r = get_role(key)
    return (r or {}).get("perms", {}) or {}


def valid_role_key(key):
    """校验角色 key：仅中英文/数字/下划线，长度<=32。"""
    if not key or len(key) > 32:
        return False
    return all(ch.isalnum() or ch == "_" or "\u4e00" <= ch <= "\u9fff" for ch in key)


def _normalize_perms(perms):
    """规范化 perms：仅保留合法模块与 0/1 标志。"""
    from campus.services.acl import module_keys
    valid_keys = set(module_keys())
    out = {}
    if not isinstance(perms, dict):
        return out
    for mk, flags in perms.items():
        if mk not in valid_keys:
            continue
        if not isinstance(flags, dict):
            continue
        out[mk] = {
            "v": 1 if flags.get("v") or flags.get("perm_visibility") else 0,
            "r": 1 if flags.get("r") or flags.get("perm_read") else 0,
            "w": 1 if flags.get("w") or flags.get("perm_write") else 0,
            "m": 1 if flags.get("m") or flags.get("perm_manage") else 0,
        }
    return out


def create_role(key, label, perms=None, bypass=False, interview_positions=None):
    key = (key or "").strip()
    label = (label or "").strip()
    if not valid_role_key(key):
        raise ValueError("角色key非法（仅支持中英文/数字/下划线，≤32字）")
    if not label:
        raise ValueError("角色名称不能为空")
    data = _read()
    roles = data.get("roles", [])
    if any(r["key"] == key for r in roles):
        raise ValueError("角色key已存在")
    entry = {
        "key": key, "label": label, "builtin": False,
        "bypass": bool(bypass),
        "perms": _normalize_perms(perms or {}),
    }
    if interview_positions is not None:
        entry["interview_positions"] = [str(x).strip() for x in interview_positions if str(x).strip()]
    roles.append(entry)
    data["roles"] = roles
    _flush(data)
    return get_role(key)


def update_role(key, label=None, perms=None, bypass=None, interview_positions=None):
    data = _read()
    roles = data.get("roles", [])
    for r in roles:
        if r["key"] == key:
            if label is not None:
                label = (label or "").strip()
                if not label:
                    raise ValueError("角色名称不能为空")
                r["label"] = label
            if bypass is not None:
                r["bypass"] = bool(bypass)
            if perms is not None:
                r["perms"] = _normalize_perms(perms)
            if interview_positions is not None:
                r["interview_positions"] = [str(x).strip() for x in interview_positions if str(x).strip()]
            data["roles"] = roles
            _flush(data)
            return get_role(key)
    raise ValueError("角色不存在")


def delete_role(key):
    data = _read()
    roles = data.get("roles", [])
    r = get_role(key)
    if not r:
        raise ValueError("角色不存在")
    if r.get("builtin"):
        raise ValueError("内置角色不可删除")
    if key == "admin":
        raise ValueError("系统管理员角色不可删除")
    data["roles"] = [x for x in roles if x["key"] != key]
    _flush(data)
    return True


def roles_payload():
    """供前端使用的角色列表（含 perms）。"""
    return [
        {
            "key": r["key"],
            "label": r["label"],
            "builtin": bool(r.get("builtin")),
            "bypass": bool(r.get("bypass")),
            "perms": r.get("perms", {}) or {},
            "interview_positions": list(r.get("interview_positions") or []),
        }
        for r in all_roles()
    ]
