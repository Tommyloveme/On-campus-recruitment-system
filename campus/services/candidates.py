# -*- coding: utf-8 -*-
import json
import sqlite3

from campus.db.connection import get_db, now_str
from campus.services.users import lookup_employee_by_username


def normalize_candidate_phone(phone):
    return str(phone or "").strip()


def group_name_map():
    return {r["id"]: r["name"] for r in get_db().execute("SELECT id, name FROM groups").fetchall()}


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
    old = json.loads(row["data"])
    sourcer = (old.get("sourcer") or "").strip()
    iface = (old.get("interface_person") or "").strip()
    sourcer_row = lookup_employee_by_username(db, sourcer) if sourcer else None
    iface_row = lookup_employee_by_username(db, iface) if iface else None
    name = old.get("name") or "—"
    return {
        "error": f"电话「{phone}」已被候选人「{name}」使用，请使用其他号码",
        "code": "phone_duplicate",
        "existing": {
            "id": row["id"],
            "name": old.get("name") or "",
            "phone": phone,
            "sourcer": sourcer,
            "interface_person": iface,
            "sourcer_display": (sourcer_row["display_name"] if sourcer_row else sourcer) if sourcer else "",
            "interface_person_display": (iface_row["display_name"] if iface_row else iface) if iface else "",
        },
    }


class PhoneDuplicateError(Exception):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get("error", "电话已存在"))


def insert_candidate_row(db, data, group_id=None, ts=None):
    """写入候选人并同步 phone 列（须保证电话唯一）。"""
    ts = ts or now_str()
    phone = normalize_candidate_phone(data.get("phone"))
    try:
        cur = db.execute(
            "INSERT INTO candidates (group_id, data, phone, created_at, updated_at) VALUES (?,?,?,?,?)",
            (group_id, json.dumps(data, ensure_ascii=False), phone or None, ts, ts),
        )
    except sqlite3.IntegrityError:
        row = find_candidate_by_phone(db, phone)
        if row:
            raise PhoneDuplicateError(phone_duplicate_payload(db, row, phone))
        raise
    return cur.lastrowid


def update_candidate_row(db, cid, data, ts=None):
    """更新候选人并同步 phone 列（须保证电话唯一）。"""
    ts = ts or now_str()
    phone = normalize_candidate_phone(data.get("phone"))
    try:
        db.execute(
            "UPDATE candidates SET data=?, phone=?, updated_at=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), phone or None, ts, cid),
        )
    except sqlite3.IntegrityError:
        row = find_candidate_by_phone(db, phone, exclude_id=cid)
        if row:
            raise PhoneDuplicateError(phone_duplicate_payload(db, row, phone))
        raise


def candidate_dict(row, group_names=None):
    data = json.loads(row["data"])
    gname = (group_names or {}).get(row["group_id"])
    if gname is None:
        r = get_db().execute("SELECT name FROM groups WHERE id=?", (row["group_id"],)).fetchone()
        gname = r["name"] if r else ""
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "group_name": gname,
        "updated_at": row["updated_at"],
        "resume_name": row["resume_name"],
        "data": data,
    }


def enrich_candidate_employee_displays(db, items):
    """为候选人列表补充拓源人/接口人姓名展示（存储仍为工号）。"""
    usernames = set()
    for c in items:
        d = c["data"]
        s = (d.get("sourcer") or "").strip()
        i = (d.get("interface_person") or "").strip()
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
        s = (d.get("sourcer") or "").strip()
        i = (d.get("interface_person") or "").strip()
        c["sourcer_display"] = name_map.get(s, s) if s else ""
        c["interface_person_display"] = name_map.get(i, i) if i else ""
    return items
