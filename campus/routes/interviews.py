# -*- coding: utf-8 -*-
"""面试日程（技术面/主管面）接口。"""
import json

from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.config_loader import get_stage_meta
from campus.db.connection import get_db, now_str
from campus.interview_schedule import expand_availability_windows, generate_time_options, parse_hm, fmt_hm
from campus.services.acl import can_edit_candidate, is_admin
from campus.services.audit import add_log
from campus.services.interviews import interview_cfg, validate_interview_type
from campus.stage_engine import compute_current_stage

bp = Blueprint("interviews", __name__)


@bp.get("/api/interview/time-options")
@login_required
def api_interview_time_options():
    ic = interview_cfg()
    opts = generate_time_options(ic["day_start"], ic["day_end"], ic["time_step_minutes"])
    return jsonify({**ic, "options": opts})


@bp.get("/api/interview/availability")
@login_required
def api_interview_availability_list():
    itype = request.args.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    user_id = request.args.get("user_id", type=int)

    sql = ("SELECT a.*, u.display_name FROM interviewer_availability a "
           "JOIN users u ON u.id=a.user_id WHERE a.interview_type=?")
    params = [itype]
    if user_id:
        sql += " AND a.user_id=?"
        params.append(user_id)
    if date_from:
        sql += " AND a.avail_date>=?"
        params.append(date_from)
    if date_to:
        sql += " AND a.avail_date<=?"
        params.append(date_to)
    sql += " ORDER BY a.avail_date, a.start_time"
    rows = get_db().execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/interview/availability")
@login_required
def api_interview_availability_create():
    b = request.get_json(force=True)
    itype = b.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    avail_date = (b.get("date") or "").strip()
    start_time = (b.get("start_time") or "").strip()
    end_time = (b.get("end_time") or "").strip()
    if not avail_date or not start_time or not end_time:
        return jsonify({"error": "请填写日期与起止时间"}), 400

    if parse_hm(start_time) + interview_cfg()["slot_minutes"] > parse_hm(end_time):
        return jsonify({"error": "起止时间间隔至少为一个面试时长（45分钟）"}), 400

    group_id = None
    db = get_db()
    db.execute(
        "INSERT INTO interviewer_availability (user_id, interview_type, avail_date, start_time, end_time, group_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (g.user["id"], itype, avail_date, start_time, end_time, group_id, now_str()),
    )
    add_log(g.user, "update",
            f"{g.user['display_name']} 设置了 {avail_date} {start_time}-{end_time} 的可面试时间（{itype}）",
            group_id=group_id)
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/interview/availability/<int:aid>")
@login_required
def api_interview_availability_delete(aid):
    db = get_db()
    row = db.execute("SELECT * FROM interviewer_availability WHERE id=?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    if row["user_id"] != g.user["id"] and not is_admin(g.user):
        return jsonify({"error": "只能删除自己的可面试时间"}), 403
    db.execute("DELETE FROM interviewer_availability WHERE id=?", (aid,))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/interview/calendar")
@login_required
def api_interview_calendar():
    itype = request.args.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    if not date_from or not date_to:
        return jsonify({"error": "请指定 from 和 to 日期"}), 400

    db = get_db()
    sql = ("SELECT a.id, a.user_id, u.display_name, a.avail_date, a.start_time, a.end_time "
           "FROM interviewer_availability a JOIN users u ON u.id=a.user_id "
           "WHERE a.interview_type=? AND a.avail_date>=? AND a.avail_date<=?")
    params = [itype, date_from, date_to]
    windows = [dict(r) for r in db.execute(sql, params).fetchall()]

    bookings = db.execute(
        "SELECT b.*, c.data AS candidate_data, u.display_name AS interviewer_name "
        "FROM interview_bookings b "
        "JOIN candidates c ON c.id=b.candidate_id "
        "JOIN users u ON u.id=b.interviewer_id "
        "WHERE b.interview_type=? AND b.avail_date>=? AND b.avail_date<=?",
        (itype, date_from, date_to),
    ).fetchall()
    booking_map = {}
    for b in bookings:
        bd = dict(b)
        bd["candidate_name"] = json.loads(bd["candidate_data"]).get("name", "")
        del bd["candidate_data"]
        booking_map[(bd["interviewer_id"], bd["start_at"])] = bd

    ic = interview_cfg()
    slots = expand_availability_windows(windows, ic["slot_minutes"], ic["time_step_minutes"], booking_map)
    return jsonify({"slots": slots, "config": ic})


@bp.post("/api/interview/book")
@login_required
def api_interview_book():
    b = request.get_json(force=True)
    itype = b.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    candidate_id = b.get("candidate_id")
    interviewer_id = b.get("interviewer_id")
    start_at = (b.get("start_at") or "").strip()
    if not candidate_id or not interviewer_id or not start_at:
        return jsonify({"error": "缺少预约参数"}), 400

    db = get_db()
    cand = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not cand:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_candidate(db, g.user, cand):
        return jsonify({"error": "无该候选人编辑权限"}), 403

    ic = interview_cfg()
    parts = start_at.split(" ")
    if len(parts) != 2:
        return jsonify({"error": "start_at 格式应为 YYYY-MM-DD HH:MM"}), 400
    avail_date, start_time = parts
    end_time = fmt_hm(parse_hm(start_time) + ic["slot_minutes"])

    exists = db.execute(
        "SELECT id FROM interview_bookings WHERE interviewer_id=? AND start_at=? AND interview_type=?",
        (interviewer_id, start_at, itype),
    ).fetchone()
    if exists:
        return jsonify({"error": "该时段已被预约"}), 400

    db.execute(
        "INSERT INTO interview_bookings (interview_type, interviewer_id, candidate_id, avail_date, "
        "start_time, end_time, start_at, booked_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (itype, interviewer_id, candidate_id, avail_date, start_time, end_time, start_at,
         g.user["id"], now_str()),
    )
    data = json.loads(cand["data"])
    status_key = "tech_interview_status" if itype == "tech_interview" else "manager_interview_status"
    time_key = "tech_interview_time" if itype == "tech_interview" else "manager_interview_time"
    interviewer_key = "tech_interviewer" if itype == "tech_interview" else "manager_interviewer"
    iv = db.execute("SELECT display_name FROM users WHERE id=?", (interviewer_id,)).fetchone()
    data[status_key] = "已预约"
    data[time_key] = avail_date
    data[interviewer_key] = iv["display_name"] if iv else ""
    compute_current_stage(data)
    db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
               (json.dumps(data, ensure_ascii=False), now_str(), candidate_id))

    cname = data.get("name", "")
    add_log(g.user, "update",
            f"{g.user['display_name']} 为「{cname}」预约了 {start_at} 的{get_stage_meta(itype)['label']}（面试官 {iv['display_name'] if iv else ''}）",
            candidate_id, cname, cand["group_id"])
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/interview/book/<int:bid>")
@login_required
def api_interview_book_cancel(bid):
    db = get_db()
    row = db.execute("SELECT * FROM interview_bookings WHERE id=?", (bid,)).fetchone()
    if not row:
        return jsonify({"error": "预约不存在"}), 404
    cand = db.execute("SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)).fetchone()
    if not can_edit_candidate(db, g.user, cand):
        return jsonify({"error": "无权限"}), 403
    db.execute("DELETE FROM interview_bookings WHERE id=?", (bid,))
    db.commit()
    return jsonify({"ok": True})
