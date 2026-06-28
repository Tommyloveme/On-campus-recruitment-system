# -*- coding: utf-8 -*-
import json

from campus.db.connection import get_db


def group_name_map():
    return {r["id"]: r["name"] for r in get_db().execute("SELECT id, name FROM groups").fetchall()}


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
