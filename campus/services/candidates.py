# -*- coding: utf-8 -*-
"""候选人存取：电话唯一性、序列化与展示补充（SQL 收敛于此）。

业务 JSON 使用中文 storage_key（见 campus.db.field_store）；读写统一经 normalize。
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta

from campus.db.connection import get_db, now_str
from campus.db.field_store import (
    denormalize_record,
    field_get,
    field_set,
    nested_view,
    normalize_record,
)


def normalize_candidate_phone(phone):
    return str(phone or "").strip()


def _prepare_candidate_data(data):
    """规范化中文键并同步索引字段到 data。"""
    data = normalize_record(dict(data or {}))
    phone = normalize_candidate_phone(field_get(data, "phone"))
    if phone:
        field_set(data, "phone", phone)
    rid = str(field_get(data, "resume_id") or "").strip()
    stage = str(field_get(data, "current_stage") or "registration").strip()
    if rid:
        field_set(data, "resume_id", rid)
    field_set(data, "current_stage", stage or "registration")
    return data, phone, rid, stage or "registration"


def _sync_pipeline(db, cid, stage, manual="", ts=None):
    ts = ts or now_str()
    stage = stage or "registration"
    prev = db.execute(
        "SELECT current_stage FROM candidate_pipeline WHERE candidate_id=?", (cid,)
    ).fetchone()
    db.execute(
        "INSERT INTO candidate_pipeline (candidate_id, current_stage, manual_stage, updated_at) "
        "VALUES (?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET "
        "current_stage=excluded.current_stage, manual_stage=excluded.manual_stage, "
        "updated_at=excluded.updated_at",
        (cid, stage, manual or "", ts),
    )
    # 阶段变化 → 记录进入时间（SLA/停留时长统计依据）
    if prev is None or prev["current_stage"] != stage:
        db.execute(
            "INSERT INTO candidate_stage_history (candidate_id, stage, entered_at) VALUES (?,?,?)",
            (cid, stage, ts),
        )


def delivery_date_from_resume_id(resume_id):
    """从简历编号解析投递日期（YYYY-MM-DD）。支持 SR20250811… 内嵌 YYYYMMDD，或历史 RS2026001 形式 YYYY+年内序号。"""
    raw = str(resume_id or "").strip().upper()
    if not raw:
        return None
    digits = re.sub(r"^[A-Z]+", "", raw)
    digits = re.sub(r"\D", "", digits)
    if not digits:
        return None
    for i in range(len(digits) - 7):
        chunk = digits[i : i + 8]
        try:
            dt = datetime.strptime(chunk, "%Y%m%d")
            if 1990 <= dt.year <= 2100:
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    if len(digits) == 7:
        year, doy = int(digits[:4]), int(digits[4:])
        if 1 <= doy <= 366:
            try:
                dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def find_candidate_by_phone(db, phone, exclude_id=None):
    """按电话查找候选人；exclude_id 用于编辑时排除自身。"""
    phone = normalize_candidate_phone(phone)
    if not phone:
        return None
    row = db.execute("SELECT * FROM candidates WHERE phone=?", (phone,)).fetchone()
    if not row:
        return None
    if exclude_id is not None and row["id"] == exclude_id:
        return None
    return row


def phone_duplicate_payload(db, row, phone):
    """电话冲突时的 API 响应体。"""
    old = normalize_record(json.loads(row["data"]))
    sourcer = str(field_get(old, "sourcer") or "").strip()
    iface = str(field_get(old, "interface_person") or "").strip()
    name = field_get(old, "name") or "—"
    return {
        "error": f"电话「{phone}」已被候选人「{name}」使用，请使用其他号码",
        "code": "phone_duplicate",
        "existing": {
            "id": row["id"],
            "name": field_get(old, "name") or "",
            "phone": phone,
            "sourcer": sourcer,
            "interface_person": iface,
            "sourcer_display": field_get(old, "sourcer_name") or sourcer,
            "interface_person_display": field_get(old, "interface_person_name") or iface,
        },
    }


class PhoneDuplicateError(Exception):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get("error", "电话已存在"))


def insert_candidate_row(db, data, group_id=None, ts=None):
    """写入候选人并同步 phone/resume_id/current_stage 与 pipeline 表。

    group_id 为历史遗留参数（资源分组已取消），仅为兼容旧调用保留、不再落库。
    """
    ts = ts or now_str()
    data, phone, rid, stage = _prepare_candidate_data(data)
    manual = str(field_get(data, "manual_stage") or field_get(data, "_手动流程阶段") or "").strip()
    try:
        cur = db.execute(
            "INSERT INTO candidates (data, phone, resume_id, current_stage, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (json.dumps(data, ensure_ascii=False), phone or None, rid or None,
             stage, ts, ts),
        )
        cid = cur.lastrowid
        _sync_pipeline(db, cid, stage, manual, ts)
        return cid
    except sqlite3.IntegrityError:
        row = find_candidate_by_phone(db, phone)
        if row:
            raise PhoneDuplicateError(phone_duplicate_payload(db, row, phone))
        raise


def update_candidate_row(db, cid, data, ts=None):
    """更新候选人并同步索引列与 pipeline 表。"""
    ts = ts or now_str()
    data, phone, rid, stage = _prepare_candidate_data(data)
    manual = str(field_get(data, "manual_stage") or field_get(data, "_手动流程阶段") or "").strip()
    try:
        db.execute(
            "UPDATE candidates SET data=?, phone=?, resume_id=?, current_stage=?, updated_at=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), phone or None, rid or None, stage, ts, cid),
        )
        _sync_pipeline(db, cid, stage, manual, ts)
    except sqlite3.IntegrityError:
        row = find_candidate_by_phone(db, phone, exclude_id=cid)
        if row:
            raise PhoneDuplicateError(phone_duplicate_payload(db, row, phone))
        raise


def delete_candidate_row(db, row):
    """删除候选人：级联清理面试预约、简历文件与两张原始表记录。"""
    from campus.services.candidate_pipeline import delete_raw_records
    from campus.services.resumes import remove_resume_file
    remove_resume_file(row["resume_file"])
    db.execute("DELETE FROM interview_bookings WHERE candidate_id=?", (row["id"],))
    db.execute("DELETE FROM candidate_pipeline WHERE candidate_id=?", (row["id"],))
    db.execute("DELETE FROM candidates WHERE id=?", (row["id"],))
    phone = row["phone"] if "phone" in row.keys() else None
    if not phone:
        phone = field_get(json.loads(row["data"]), "phone")
    delete_raw_records(db, normalize_candidate_phone(phone))


def merge_candidate_rows(db, edited_row, edited_data, target_row):
    """双手机号合并（编辑电话撞上已有候选人时触发）。

    场景：Application 表注册的手机号与手动录入的不一致，实为同一人；
    用户把手动记录的电话改成主数据电话后确认合并。
    规则：重复字段优先使用主数据表导入侧的数据；保留主数据侧的行
    （锁定字段/主数据关联不丢），另一行的简历、面试预约转移后删除。
    返回 (保留行id, 合并后data)。
    """
    from campus.services.candidate_pipeline import delete_raw_records, record_manual
    from campus.domain.stage_routing import compute_current_stage

    target_data = normalize_record(json.loads(target_row["data"]))
    edited_data = normalize_record(edited_data)
    edited_master = bool(field_get(edited_data, "_master_imported"))
    target_master = bool(field_get(target_data, "_master_imported"))
    if edited_master and not target_master:
        keep_row, keep_data = edited_row, edited_data
        drop_row, drop_data = target_row, target_data
    else:
        keep_row, keep_data = target_row, target_data
        drop_row, drop_data = edited_row, edited_data

    # 合并：非主数据侧为底，主数据侧非空值覆盖（内部簿记键随主数据侧）
    merged = {k: v for k, v in drop_data.items() if not k.startswith("_")}
    for k, v in keep_data.items():
        if k.startswith("_") or str(v or "").strip():
            merged[k] = v
    final_phone = normalize_candidate_phone(
        target_row["phone"] or field_get(target_data, "phone"))
    field_set(merged, "phone", final_phone)
    compute_current_stage(merged)

    # 简历转移：保留行没有简历而被删行有 → 挪过去
    if not keep_row["resume_file"] and drop_row["resume_file"]:
        db.execute("UPDATE candidates SET resume_file=?, resume_name=? WHERE id=?",
                   (drop_row["resume_file"], drop_row["resume_name"], keep_row["id"]))

    # 面试预约转移到保留行（撞唯一约束的预约放弃转移）
    for bk in db.execute("SELECT id FROM interview_bookings WHERE candidate_id=?",
                         (drop_row["id"],)).fetchall():
        try:
            db.execute("UPDATE interview_bookings SET candidate_id=? WHERE id=?",
                       (keep_row["id"], bk["id"]))
        except sqlite3.IntegrityError:
            db.execute("DELETE FROM interview_bookings WHERE id=?", (bk["id"],))

    # 删除被合并行及其旧电话的原始表记录（不删简历文件，已转移或保留行自有）
    db.execute("DELETE FROM candidates WHERE id=?", (drop_row["id"],))
    drop_phone = normalize_candidate_phone(drop_row["phone"] or drop_data.get("phone"))
    if drop_phone and drop_phone != final_phone:
        delete_raw_records(db, drop_phone)

    update_candidate_row(db, keep_row["id"], merged)
    record_manual(db, final_phone, merged)
    return keep_row["id"], merged


def candidate_dict(row):
    data = normalize_record(json.loads(row["data"]))
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "id": row["id"],
        "updated_at": row["updated_at"],
        "resume_name": row["resume_name"],
        "phone": row["phone"] if "phone" in keys else field_get(data, "phone"),
        "resume_id": row["resume_id"] if "resume_id" in keys else field_get(data, "resume_id"),
        "current_stage": row["current_stage"] if "current_stage" in keys else field_get(data, "current_stage"),
        # 双键视图：中文 storage_key 为准，同时附带 legacy 英文键（API 兼容）
        "data": denormalize_record(data),
        "data_nested": nested_view(data),
    }


def enrich_candidate_employee_displays(db, items):
    """为候选人列表补充拓源人/接口人姓名展示（存储仍为工号）。"""
    usernames = set()
    for c in items:
        d = c["data"]
        s = str(field_get(d, "sourcer") or "").strip()
        i = str(field_get(d, "interface_person") or "").strip()
        if s:
            usernames.add(s)
        if i:
            usernames.add(i)
    if not usernames:
        return items
    ph = ",".join("?" * len(usernames))
    rows = db.execute(
        f"SELECT username, display_name FROM users WHERE username IN ({ph})",
        list(usernames),
    ).fetchall()
    name_map = {r["username"]: r["display_name"] for r in rows}
    for c in items:
        d = c["data"]
        s = str(field_get(d, "sourcer") or "").strip()
        i = str(field_get(d, "interface_person") or "").strip()
        c["sourcer_display"] = name_map.get(s, s) if s else ""
        c["interface_person_display"] = name_map.get(i, i) if i else ""
    return items
