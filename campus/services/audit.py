# -*- coding: utf-8 -*-
from campus.db.connection import get_db, now_str


def add_log(user, action, message, candidate_id=None, candidate_name=None, group_id=None):
    get_db().execute(
        "INSERT INTO logs (user_name, action, candidate_id, candidate_name, group_id, message, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (user["display_name"], action, candidate_id, candidate_name, group_id, message, now_str()),
    )
