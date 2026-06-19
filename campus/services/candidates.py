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


def user_dict(u):
    group_name = None
    if u["group_id"]:
        row = get_db().execute("SELECT name FROM groups WHERE id=?", (u["group_id"],)).fetchone()
        group_name = row["name"] if row else None
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "role": u["role"],
        "group_id": u["group_id"],
        "group_name": group_name,
    }
