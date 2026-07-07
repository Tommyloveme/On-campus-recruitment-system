# -*- coding: utf-8 -*-
"""候选人数据管道（唯一实现，勿在其他地方重复合并逻辑）。

数据流（主键 = 电话号码）：

    candidates_raw_manual（手动录入原始表）─┐
                                            ├─ 合并（主数据优先）→ 预处理 → candidates（原始数据预处理表）
    candidates_raw_master（主数据导入原始表）┘

- 手动录入/页面编辑 → record_manual()；主数据表刷新 → record_master()。
- 合并规则：以手动数据为底，主数据表非空字段覆盖（merge_master_import_data，
  锁定字段记入 _master_locked_fields，页面编辑时被拦截）。
- 预处理：compute_current_stage 依据状态列推导 current_stage，
  候选人登记/校招流程/Offer策略/入职管理各页面均按该列过滤展示；
  各页面对候选人的更新写回 candidates 并同步 raw_manual。
- 并发：SQLite WAL + busy_timeout（db/connection.py），candidates.phone 唯一索引
  兜底防止并发重复建档；raw 表以 phone 为主键，UPSERT 天然幂等。
"""
import json

from campus.db.connection import now_str

#: 内部簿记键（不属于原始数据，不进 raw 表）
_INTERNAL_PREFIX = "_"


def _clean(data):
    return {k: v for k, v in (data or {}).items() if not k.startswith(_INTERNAL_PREFIX)}


def _upsert_raw(db, table, phone, data, ts=None):
    ts = ts or now_str()
    db.execute(
        f"INSERT INTO {table} (phone, data, created_at, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(phone) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (phone, json.dumps(data, ensure_ascii=False), ts, ts),
    )


def _load_raw(db, table, phone):
    row = db.execute(f"SELECT data FROM {table} WHERE phone=?", (phone,)).fetchone()
    return json.loads(row["data"]) if row else None


def record_manual(db, phone, data, ts=None):
    """记录一次手动录入/编辑的结果快照到手动原始表。"""
    if phone:
        _upsert_raw(db, "candidates_raw_manual", phone, _clean(data), ts)


def record_master(db, phone, data, ts=None):
    """记录一次主数据表导入的行数据到主数据原始表。"""
    if phone:
        _upsert_raw(db, "candidates_raw_master", phone, _clean(data), ts)


def merge_raw_sources(manual, master, cfg=None):
    """合并两个原始表的数据：以手动为底、主数据优先覆盖（纯函数）。"""
    from campus.services.master_import import merge_master_import_data
    if not master:
        return dict(manual or {})
    return merge_master_import_data(dict(manual or {}), dict(master), cfg)


def rebuild_candidate(db, phone, cfg=None):
    """按电话重建预处理表行：raw_manual ⊕ raw_master → 预处理 → candidates。

    返回候选人 id；两个原始表都没有该电话时返回 None。
    """
    from campus.domain.stage_routing import compute_current_stage
    from campus.services.candidates import (
        find_candidate_by_phone,
        insert_candidate_row,
        update_candidate_row,
    )

    manual = _load_raw(db, "candidates_raw_manual", phone)
    master = _load_raw(db, "candidates_raw_master", phone)
    if manual is None and master is None:
        return None
    merged = merge_raw_sources(manual, master, cfg)
    merged["phone"] = phone
    compute_current_stage(merged)

    row = find_candidate_by_phone(db, phone)
    if row:
        update_candidate_row(db, row["id"], merged)
        return row["id"]
    return insert_candidate_row(db, merged)


def delete_raw_records(db, phone):
    """删除候选人时同步清理两个原始表（由 delete_candidate_row 调用）。"""
    if phone:
        db.execute("DELETE FROM candidates_raw_manual WHERE phone=?", (phone,))
        db.execute("DELETE FROM candidates_raw_master WHERE phone=?", (phone,))
