# -*- coding: utf-8 -*-
"""面试日程（技术面/主管面）接口。"""
import json
import sqlite3

from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.config_loader import get_stage_meta
from campus.db.connection import get_db, now_str
from campus.interview_schedule import (
    expand_availability_windows,
    find_overlapping_window,
    format_availability_window,
    generate_slot_start_options,
    generate_time_options,
    parse_hm,
    fmt_hm,
)
from campus.services.acl import can_edit_candidate, is_admin, module_writable_for
from campus.services.audit import add_log
from campus.services.candidates import find_candidate_by_phone, normalize_candidate_phone
from campus.services.interviews import (
    interview_cfg,
    interviewer_matches_position,
    parse_job_roles,
    validate_interview_type,
)
from campus.services.users import lookup_employee_for_registration
from campus.settings import load_app_config
from campus.stage_engine import compute_current_stage

bp = Blueprint("interviews", __name__)


def _slot_minutes_from_request(default):
    raw = request.args.get("slot_minutes") if request.method == "GET" else None
    if raw is None and request.method != "GET":
        body = request.get_json(silent=True) or {}
        raw = body.get("slot_minutes")
    try:
        val = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        val = default
    return max(15, min(180, val))


def _user_job_roles(db, user_id):
    row = db.execute("SELECT job_roles FROM users WHERE id=?", (user_id,)).fetchone()
    return parse_job_roles(row["job_roles"] if row else None)


@bp.get("/api/interview/time-options")
@login_required
def api_interview_time_options():
    ic = interview_cfg()
    slot_minutes = _slot_minutes_from_request(ic["slot_minutes"])
    opts = generate_time_options(ic["day_start"], ic["day_end"], ic["time_step_minutes"])
    slot_starts = generate_slot_start_options(ic["day_start"], ic["day_end"], slot_minutes)
    return jsonify({**ic, "options": opts, "slot_starts": slot_starts, "slot_minutes": slot_minutes})


@bp.get("/api/interview/candidate-by-phone")
@login_required
def api_interview_candidate_by_phone():
    phone = normalize_candidate_phone(request.args.get("phone"))
    if not phone:
        return jsonify({"error": "请填写候选人电话"}), 400
    db = get_db()
    row = find_candidate_by_phone(db, phone)
    if not row:
        return jsonify({"error": f"电话「{phone}」未找到对应候选人", "found": False}), 404
    data = json.loads(row["data"])
    return jsonify({
        "found": True,
        "id": row["id"],
        "name": data.get("name") or "",
        "phone": phone,
        "interview_position": data.get("interview_position") or "",
    })


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

    sql = ("SELECT a.*, u.display_name, u.job_roles FROM interviewer_availability a "
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
    out = []
    for r in rows:
        d = dict(r)
        d["job_roles"] = parse_job_roles(d.get("job_roles"))
        out.append(d)
    return jsonify(out)


def _parse_availability_start_times(body, slot_minutes):
    """解析可面试开始时刻：优先 start_times 多选，兼容 start_time/end_time 区间。"""
    raw_list = body.get("start_times")
    if isinstance(raw_list, list):
        times = sorted({str(t).strip() for t in raw_list if str(t).strip()})
        if times:
            return times, None
    start_time = (body.get("start_time") or "").strip()
    end_time = (body.get("end_time") or "").strip()
    if start_time and not end_time:
        return [start_time], None
    if start_time and end_time:
        if parse_hm(start_time) + slot_minutes > parse_hm(end_time):
            return None, f"起止时间间隔至少为一个面试时长（{slot_minutes} 分钟）"
        from campus.interview_schedule import generate_bookable_slots
        slots = generate_bookable_slots(
            (body.get("date") or "").strip(), start_time, end_time, slot_minutes,
            interview_cfg()["time_step_minutes"],
        )
        return sorted({s["start"] for s in slots}), None
    return None, "请至少选择一个可面试开始时间"


def _parse_availability_entries(body, default_slot_minutes):
    """解析可面试时段：entries 多行（每行 date/start_time/slot_minutes），或兼容 start_times。"""
    entries = body.get("entries")
    if isinstance(entries, list) and entries:
        parsed = []
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            avail_date = (e.get("date") or "").strip()
            start_time = (e.get("start_time") or "").strip()
            if not avail_date or not start_time:
                continue
            try:
                sm = int(e.get("slot_minutes", default_slot_minutes))
            except (TypeError, ValueError):
                sm = default_slot_minutes
            sm = max(15, min(180, sm))
            parsed.append({"date": avail_date, "start_time": start_time, "slot_minutes": sm})
        if not parsed:
            return None, "请至少填写一行完整的可面试时间（日期与开始时间）"
        return parsed, None

    ic = interview_cfg()
    slot_minutes = _slot_minutes_from_request(default_slot_minutes)
    start_times, err = _parse_availability_start_times(body, slot_minutes)
    if err:
        return None, err
    avail_date = (body.get("date") or "").strip()
    if not avail_date:
        return None, "请填写日期"
    return [
        {"date": avail_date, "start_time": t, "slot_minutes": slot_minutes}
        for t in start_times
    ], None


def _validate_availability_no_overlap(db, user_id, itype, entries, iv_name):
    """校验新录入时段与同面试官已有/同批次时段不重叠。"""
    dates = sorted({e["date"] for e in entries})
    if not dates:
        return None
    placeholders = ",".join("?" * len(dates))
    existing = [
        dict(r) for r in db.execute(
            f"SELECT avail_date, start_time, end_time FROM interviewer_availability "
            f"WHERE user_id=? AND interview_type=? AND avail_date IN ({placeholders})",
            [user_id, itype, *dates],
        ).fetchall()
    ]
    pending = []
    for entry in entries:
        avail_date = entry["date"]
        start_time = entry["start_time"]
        end_time = fmt_hm(parse_hm(start_time) + entry["slot_minutes"])
        new_label = format_availability_window(avail_date, start_time, end_time)

        hit = find_overlapping_window(existing, avail_date, start_time, end_time)
        if hit:
            old_label = format_availability_window(
                hit["avail_date"], hit["start_time"], hit["end_time"],
            )
            return f"面试官「{iv_name}」的可面试时间 {new_label} 与已有时段 {old_label} 重叠，无法录入"

        hit = find_overlapping_window(pending, avail_date, start_time, end_time)
        if hit:
            old_label = format_availability_window(
                hit["avail_date"], hit["start_time"], hit["end_time"],
            )
            return f"本次录入的时段 {new_label} 与 {old_label} 重叠，无法录入"

        pending.append({
            "avail_date": avail_date,
            "start_time": start_time,
            "end_time": end_time,
        })
    return None


@bp.post("/api/interview/availability")
@login_required
def api_interview_availability_create():
    b = request.get_json(force=True)
    itype = b.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    ic = interview_cfg()
    default_sm = ic["slot_minutes"]
    entries, err = _parse_availability_entries(b, default_sm)
    if err:
        return jsonify({"error": err}), 400

    db = get_db()
    interviewer_q = (b.get("interviewer") or b.get("interviewer_query") or "").strip()
    if interviewer_q:
        iv_row = lookup_employee_for_registration(db, interviewer_q)
        if not iv_row:
            return jsonify({"error": "未找到该面试官，请填写已注册用户的工号或姓名"}), 400
        user_id = iv_row["id"]
        iv_name = iv_row["display_name"]
    else:
        user_id = g.user["id"]
        iv_name = g.user["display_name"]

    overlap_err = _validate_availability_no_overlap(db, user_id, itype, entries, iv_name)
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    created = 0
    for entry in entries:
        avail_date = entry["date"]
        start_time = entry["start_time"]
        slot_minutes = entry["slot_minutes"]
        end_time = fmt_hm(parse_hm(start_time) + slot_minutes)
        try:
            db.execute(
                "INSERT INTO interviewer_availability (user_id, interview_type, avail_date, start_time, end_time, group_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (user_id, itype, avail_date, start_time, end_time, None, now_str()),
            )
            created += 1
        except sqlite3.IntegrityError:
            return jsonify({"error": "该时段已被他人录入，请刷新后重试"}), 409

    add_log(g.user, "update",
            f"{g.user['display_name']} 为面试官「{iv_name}」设置了 {created} 段可面试时间（{itype}）")
    db.commit()
    return jsonify({"ok": True, "created": created})


def _can_manage_availability(user, itype, owner_user_id):
    if is_admin(user):
        return True
    if user["id"] == owner_user_id:
        return True
    return module_writable_for(user, itype)


@bp.delete("/api/interview/availability/<int:aid>")
@login_required
def api_interview_availability_delete(aid):
    db = get_db()
    row = db.execute("SELECT * FROM interviewer_availability WHERE id=?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    if not _can_manage_availability(g.user, row["interview_type"], row["user_id"]):
        return jsonify({"error": "无权限删除该可面试时间"}), 403
    booked = db.execute(
        "SELECT id FROM interview_bookings WHERE interviewer_id=? AND interview_type=? "
        "AND avail_date=? AND start_time=?",
        (row["user_id"], row["interview_type"], row["avail_date"], row["start_time"]),
    ).fetchone()
    if booked:
        return jsonify({"error": "该时段已有预约，请先取消预约后再删除"}), 400
    iv = db.execute("SELECT display_name FROM users WHERE id=?", (row["user_id"],)).fetchone()
    iv_name = iv["display_name"] if iv else str(row["user_id"])
    db.execute("DELETE FROM interviewer_availability WHERE id=?", (aid,))
    add_log(g.user, "update",
            f"{g.user['display_name']} 删除了面试官「{iv_name}」"
            f" {row['avail_date']} {row['start_time']} 的可面试时间（{row['interview_type']}）")
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
    position = (request.args.get("position") or "").strip()
    department = (request.args.get("department") or "").strip()
    if not date_from or not date_to:
        return jsonify({"error": "请指定 from 和 to 日期"}), 400

    db = get_db()
    ic = interview_cfg()
    slot_minutes = _slot_minutes_from_request(ic["slot_minutes"])

    sql = ("SELECT a.id, a.user_id, u.display_name, u.job_roles, u.dept_level2, u.department, "
           "a.avail_date, a.start_time, a.end_time "
           "FROM interviewer_availability a JOIN users u ON u.id=a.user_id "
           "WHERE a.interview_type=? AND a.avail_date>=? AND a.avail_date<=?")
    params = [itype, date_from, date_to]
    windows = []
    for r in db.execute(sql, params).fetchall():
        d = dict(r)
        d["job_roles"] = parse_job_roles(d.get("job_roles"))
        if department and (d.get("dept_level2") or "").strip() != department:
            continue
        if not interviewer_matches_position(d["job_roles"], position):
            continue
        windows.append(d)

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
        cdata = json.loads(bd["candidate_data"])
        bd["candidate_name"] = cdata.get("name", "")
        bd["candidate_phone"] = cdata.get("phone", "")
        bd["interview_position"] = cdata.get("interview_position", "")
        del bd["candidate_data"]
        if position and bd.get("interview_position") and bd["interview_position"] != position:
            continue
        booking_map[(bd["interviewer_id"], bd["start_at"])] = bd

    slots = expand_availability_windows(windows, slot_minutes, ic["time_step_minutes"], booking_map)
    if position:
        slots = [s for s in slots if not s.get("booking") or s["booking"].get("interview_position") in ("", position)]

    cfg_depts = load_app_config().get("user_profile", {}).get("dept_level2_options") or []
    db_depts = [
        r["dept_level2"] for r in db.execute(
            "SELECT DISTINCT u.dept_level2 FROM interviewer_availability a "
            "JOIN users u ON u.id=a.user_id "
            "WHERE a.interview_type=? AND a.avail_date>=? AND a.avail_date<=? "
            "AND TRIM(COALESCE(u.dept_level2, '')) != ''",
            (itype, date_from, date_to),
        ).fetchall()
    ]
    departments = sorted({d for d in cfg_depts + db_depts if d})

    return jsonify({
        "slots": slots,
        "config": {**ic, "slot_minutes": slot_minutes},
        "filter_options": {"departments": departments},
    })


@bp.post("/api/interview/book")
@login_required
def api_interview_book():
    b = request.get_json(force=True)
    itype = b.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db = get_db()
    candidate_id = b.get("candidate_id")
    phone = normalize_candidate_phone(b.get("phone"))
    if phone:
        cand = find_candidate_by_phone(db, phone)
        if not cand:
            return jsonify({"error": f"电话「{phone}」未找到对应候选人，无法预约"}), 404
        candidate_id = cand["id"]
    elif candidate_id:
        cand = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    else:
        return jsonify({"error": "请填写候选人电话"}), 400

    if not cand:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_candidate(db, g.user, cand):
        return jsonify({"error": "无该候选人编辑权限"}), 403

    interviewer_id = b.get("interviewer_id")
    start_at = (b.get("start_at") or "").strip()
    if not interviewer_id or not start_at:
        return jsonify({"error": "缺少预约参数"}), 400

    ic = interview_cfg()
    slot_minutes = _slot_minutes_from_request(ic["slot_minutes"])
    parts = start_at.split(" ")
    if len(parts) != 2:
        return jsonify({"error": "start_at 格式应为 YYYY-MM-DD HH:MM"}), 400
    avail_date, start_time = parts
    avail_row = db.execute(
        "SELECT end_time FROM interviewer_availability WHERE user_id=? AND interview_type=? "
        "AND avail_date=? AND start_time=?",
        (interviewer_id, itype, avail_date, start_time),
    ).fetchone()
    end_time = avail_row["end_time"] if avail_row else fmt_hm(parse_hm(start_time) + slot_minutes)

    try:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute(
            "SELECT id FROM interview_bookings WHERE interviewer_id=? AND start_at=? AND interview_type=?",
            (interviewer_id, start_at, itype),
        ).fetchone()
        if exists:
            db.rollback()
            return jsonify({"error": "该时段已被预约，请刷新后重试"}), 409

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
        data[time_key] = start_at
        data[interviewer_key] = iv["display_name"] if iv else ""
        compute_current_stage(data)
        db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                   (json.dumps(data, ensure_ascii=False), now_str(), candidate_id))

        cname = data.get("name", "")
        add_log(g.user, "update",
                f"{g.user['display_name']} 为「{cname}」（{data.get('phone', '')}）预约了 {start_at} 的"
                f"{get_stage_meta(itype)['label']}（面试官 {iv['display_name'] if iv else ''}）",
                candidate_id, cname, cand["group_id"])
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"error": "该时段已被他人预约，请刷新后重试"}), 409

    return jsonify({"ok": True})


@bp.delete("/api/interview/book/<int:bid>")
@login_required
def api_interview_book_cancel(bid):
    db = get_db()
    row = db.execute("SELECT * FROM interview_bookings WHERE id=?", (bid,)).fetchone()
    if not row:
        return jsonify({"error": "预约不存在"}), 404
    cand = db.execute("SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)).fetchone()
    if not cand:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_candidate(db, g.user, cand):
        return jsonify({"error": "无权限"}), 403

    itype = row["interview_type"]
    data = json.loads(cand["data"])
    status_key = "tech_interview_status" if itype == "tech_interview" else "manager_interview_status"
    time_key = "tech_interview_time" if itype == "tech_interview" else "manager_interview_time"
    interviewer_key = "tech_interviewer" if itype == "tech_interview" else "manager_interviewer"
    cname = data.get("name", "")

    db.execute("DELETE FROM interview_bookings WHERE id=?", (bid,))
    data[status_key] = "待预约"
    data[time_key] = ""
    data[interviewer_key] = ""
    compute_current_stage(data)
    db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
               (json.dumps(data, ensure_ascii=False), now_str(), cand["id"]))
    add_log(g.user, "update",
            f"{g.user['display_name']} 取消了「{cname}」的 {row['start_at']} 面试预约（{get_stage_meta(itype)['label']}）",
            cand["id"], cname, cand["group_id"])
    db.commit()
    return jsonify({"ok": True})
