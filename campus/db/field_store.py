# -*- coding: utf-8 -*-
"""数据库字段存取层（唯一入口）：中文键存储 + 嵌套路径配置 + 英文兼容。

- 候选人等业务 JSON 以 **中文 storage_key** 为 canonical 形式持久化；
- 未在注册表中的英文键（如 Excel 自动入库列）原样保留，不做改写；
- 外部可通过嵌套路径（如 ``候选人.流程.Offer状态``）读写，层数不限；
- 配置：``config/db/field_registry.json``（由 ``build_field_registry`` 生成/维护）。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from campus.core.settings import BASE_DIR

REGISTRY_PATH = os.path.join(BASE_DIR, "config", "db", "field_registry.json")
TABLE_REGISTRY_PATH = os.path.join(BASE_DIR, "config", "db", "table_registry.json")

# 内部簿记键（英文 legacy → 中文 storage）
_INTERNAL_LEGACY = {
    "_master_imported": "_主数据已导入",
    "_master_locked_fields": "_主数据锁定字段",
    "manual_stage": "_手动流程阶段",
}


@lru_cache(maxsize=1)
def load_field_registry():
    if not os.path.isfile(REGISTRY_PATH):
        build_field_registry(save=True)
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_table_registry():
    if not os.path.isfile(TABLE_REGISTRY_PATH):
        return {"tables": {}, "version": 1}
    with open(TABLE_REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def reload_field_registry():
    load_field_registry.cache_clear()
    load_table_registry.cache_clear()
    _normalize_maps.cache_clear()


@lru_cache(maxsize=1)
def _normalize_maps():
    """(legacy→storage 翻译表, 已注册键集合)。

    normalize_record / legacy_to_storage 在导入链路中逐行逐键调用，
    预构建平坦 dict 比每次遍历注册表快一个数量级。
    """
    reg = load_field_registry()
    fm = reg.get("fields") or {}
    trans = {leg: (meta.get("storage_key") or leg) for leg, meta in fm.items()}
    trans.update(_INTERNAL_LEGACY)
    registered = set(fm) | set(reg.get("legacy_index") or {})
    return trans, registered


def _fields_map(reg=None):
    reg = reg or load_field_registry()
    return reg.get("fields") or {}


def _path_index(reg=None):
    reg = reg or load_field_registry()
    return reg.get("paths") or {}


def legacy_to_storage(key: str, reg=None) -> str:
    """英文 legacy_key / 旧配置 key → 中文 storage_key；未知键原样返回。"""
    if not key:
        return key
    if reg is None:
        trans, _ = _normalize_maps()
        return trans.get(key, key)
    if key.startswith("_") and key in _INTERNAL_LEGACY:
        return _INTERNAL_LEGACY[key]
    entry = _fields_map(reg).get(key)
    if entry:
        return entry.get("storage_key") or key
    return key


def storage_to_legacy(key: str, reg=None) -> str:
    """中文 storage_key → legacy_key（若存在映射）。"""
    if not key:
        return key
    rev = (load_field_registry() if reg is None else reg).get("legacy_index") or {}
    if key in rev:
        return rev[key]
    for leg, cn in _INTERNAL_LEGACY.items():
        if cn == key:
            return leg
    return key


def resolve_path(path: str, reg=None) -> str:
    """嵌套路径 ``A.B.C`` → 扁平 storage_key；已是扁平中文键则直接返回。"""
    path = (path or "").strip()
    if not path:
        return path
    idx = _path_index(reg)
    if path in idx:
        return idx[path]
    parts = path.split(".")
    if len(parts) == 1:
        return legacy_to_storage(path, reg)
    # 按路径后缀在 path_index 中匹配
    for i in range(len(parts)):
        sub = ".".join(parts[i:])
        if sub in idx:
            return idx[sub]
    return parts[-1]


def field_get(record: dict | None, key_or_path: str, default=""):
    """从记录读取字段（支持 legacy 英文、中文扁平键、嵌套路径）。

    拓源人信息/接口人信息：兼容旧「部门」+「PL组」两列，读时自动合并。
    """
    if not record or not key_or_path:
        return default
    sk = resolve_path(key_or_path)
    if sk in record:
        v = record.get(sk)
        return default if v is None else v
    leg = storage_to_legacy(sk)
    if leg != sk and leg in record:
        v = record.get(leg)
        return default if v is None else v
    if key_or_path in record:
        v = record.get(key_or_path)
        return default if v is None else v
    leg2 = legacy_to_storage(key_or_path)
    if leg2 in record:
        v = record.get(leg2)
        return default if v is None else v
    # 旧「部门」+「PL组」→「信息」读时合并
    from campus.domain.employees import DEPT_INFO_ALIASES, merge_dept_pl_text
    for cn, en, old_dept, pl_keys in DEPT_INFO_ALIASES:
        if key_or_path in (cn, en, old_dept) or sk in (cn, en, old_dept) or leg2 in (cn, en):
            dept = str(record.get(old_dept) or record.get(en) or "").strip()
            pl = ""
            for pk in pl_keys:
                pl = pl or str(record.get(pk) or "").strip()
            merged = merge_dept_pl_text(dept, pl)
            if merged:
                return merged
            break
    return default


def field_set(record: dict, key_or_path: str, value) -> dict:
    """写入字段（canonical 中文 storage_key）。"""
    sk = resolve_path(key_or_path)
    record[sk] = value
    leg = storage_to_legacy(sk)
    if leg != sk and leg in record:
        del record[leg]
    return record


def is_registered_key(key: str, reg=None) -> bool:
    fm = _fields_map(reg)
    if key in fm:
        return True
    if key in (load_field_registry() if reg is None else reg).get("legacy_index", {}):
        return True
    return key in _INTERNAL_LEGACY or key in _INTERNAL_LEGACY.values()


def normalize_record(record: dict | None, *, drop_legacy: bool = True) -> dict:
    """将已知英文键转为中文 storage_key；未注册键（含英文自动列）保留不动。"""
    if not record:
        return {}
    trans, registered = _normalize_maps()
    out = {}
    for k, v in record.items():
        if k.startswith("_") and k not in _INTERNAL_LEGACY:
            out[k] = v
            continue
        sk = trans.get(k, k)
        if isinstance(v, dict) and not k.startswith("_") and (k in registered or k in trans):
            out[sk] = normalize_record(v, drop_legacy=drop_legacy)
        else:
            out[sk] = v
    if drop_legacy:
        for leg, cn in trans.items():
            if cn != leg and leg in out and cn in out:
                del out[leg]
    return out


def denormalize_record(record: dict | None) -> dict:
    """API 兼容：中文 storage → legacy 英文键（双写视图，便于渐进迁移）。

    浅拷贝即可：结果只用于 JSON 序列化，legacy 键与中文键共享值对象；
    列表接口逐行 deepcopy 万级数据会明显拖慢响应。
    """
    if not record:
        return {}
    out = dict(record)
    reg = load_field_registry()
    rev = reg.get("legacy_index") or {}
    for cn, leg in rev.items():
        if cn in out and leg not in out:
            out[leg] = out[cn]
    for leg, cn in _INTERNAL_LEGACY.items():
        if cn in out and leg not in out:
            out[leg] = out[cn]
    return out


def nested_view(record: dict | None, reg=None) -> dict:
    """按 field_registry 中的 path 构建嵌套视图（外部配置用）。"""
    reg = reg or load_field_registry()
    tree: dict = {}
    flat = normalize_record(record or {}, drop_legacy=False)
    for leg, meta in (reg.get("fields") or {}).items():
        sk = meta.get("storage_key") or leg
        path = meta.get("path") or []
        val = flat.get(sk)
        if val is None:
            val = flat.get(leg)
        if val is None:
            continue
        node = tree
        for part in path[:-1]:
            node = node.setdefault(part, {})
        if path:
            node[path[-1]] = val
    extras = reg.get("extras_bucket") or "扩展字段"
    for k, v in flat.items():
        if k.startswith("_"):
            tree.setdefault("_内部", {})[k] = v
            continue
        known = k in (reg.get("legacy_index") or {}) or k in _fields_map(reg)
        known = known or any(
            (meta.get("storage_key") or lk) == k
            for lk, meta in (reg.get("fields") or {}).items()
        )
        if not known:
            tree.setdefault(extras, {})[k] = v
    return tree


def build_field_registry(save: bool = False) -> dict:
    """从阶段字段 + 主数据映射汇总生成 field_registry.json。"""
    from campus.core.master_import_config import (
        load_master_import_config,
        master_field_label_map,
    )
    from campus.core.stage_config import load_stages_meta

    fields = {}
    path_index = {}
    # noqa: 下方按「主数据标签优先 → 阶段标签 → 加序号」策略挑选唯一 storage_key

    def _category_for(key, label):
        if key == "current_stage" or "status" in key or "result" in key:
            return ["候选人", "流程状态"]
        if key in ("name", "phone", "email", "education", "school", "major", "resume_id"):
            return ["候选人", "基本信息"]
        if "interview" in key or "test" in key or "written" in key:
            return ["候选人", "面试测评"]
        if key.startswith("offer") or key in ("sign_status", "contract_signing_status"):
            return ["候选人", "Offer签约"]
        if "onboard" in key or key == "dept_level3":
            return ["候选人", "入职"]
        if "registration" in key or "delivery" in key or "sourcer" in key or "interface" in key:
            return ["候选人", "登记拓源"]
        return ["候选人", "扩展"]

    # 主数据映射中文列名优先作为 storage_key（更精确，如 签约情况状态 / 签约状态）
    try:
        master_labels = master_field_label_map(
            load_master_import_config("registration").get("field_mappings") or {})
    except (ValueError, OSError):
        master_labels = {}

    used_storage = set()

    def _pick_storage(k, stage_label):
        for cand in (master_labels.get(k, "").strip(), stage_label, k):
            if cand and cand not in used_storage:
                return cand
        base = stage_label or k
        n = 2
        while f"{base}{n}" in used_storage:
            n += 1
        return f"{base}{n}"

    # 直接读原始阶段字段 JSON（不经 load_stage_fields，避免其反向依赖注册表）
    from campus.core.stage_config import _load_raw_fields, COMMON_STAGE
    for stage in load_stages_meta():
        raw = _load_raw_fields(COMMON_STAGE) + _load_raw_fields(stage["key"])
        for f in raw:
            k = (f.get("key") or "").strip()
            if not k or k in fields:
                continue
            label = (f.get("label") or k).strip()
            storage = _pick_storage(k, label)
            used_storage.add(storage)
            path = _category_for(k, label) + [storage]
            fields[k] = {
                "legacy_key": k,
                "storage_key": storage,
                "label": storage,
                "path": path,
                "stages": [stage["key"]],
            }
            path_index[".".join(path)] = storage

    for k, label in master_labels.items():
        if not k or k.startswith("_") or k in fields:
            continue
        label = (label or k).strip()
        storage = _pick_storage(k, label)
        used_storage.add(storage)
        path = _category_for(k, label) + [storage]
        fields[k] = {
            "legacy_key": k,
            "storage_key": storage,
            "label": storage,
            "path": path,
            "stages": ["registration"],
        }
        path_index[".".join(path)] = storage

    # 系统派生字段（非 Excel 列，由服务端补全的展示字段）
    # 注：拓源人/接口人 PL 已合并进「部门」列（部门/PL），不再单列
    for k, label, cat in (("sourcer_name", "拓源人姓名", "登记拓源"),
                          ("interface_person_name", "接口人姓名", "登记拓源"),
                          ("process_status", "流程状态", "流程状态"),
                          ("process_terminated", "流程终止", "流程状态")):
        if k not in fields and label not in used_storage:
            used_storage.add(label)
            path = ["候选人", cat, label]
            fields[k] = {
                "legacy_key": k, "storage_key": label, "label": label,
                "path": path, "stages": ["registration"],
            }
            path_index[".".join(path)] = label

    legacy_index = {meta["storage_key"]: leg for leg, meta in fields.items()}

    reg = {
        "version": 1,
        "comment": "字段注册表：legacy_key 为历史英文键，storage_key 为数据库 JSON 中文键，path 为嵌套配置路径。",
        "fields": fields,
        "paths": path_index,
        "legacy_index": legacy_index,
        "extras_bucket": "扩展字段",
        "internal_keys": _INTERNAL_LEGACY,
    }

    if save:
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
    return reg
