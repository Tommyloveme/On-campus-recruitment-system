# -*- coding: utf-8 -*-
"""面试日程（技术面/主管面）接口：参数解析 + 权限校验，业务在 services.interviews。"""
import json

from flask import Blueprint, g, jsonify, request

from campus.db.connection import get_db
from campus.domain.interview_slots import (
    generate_bookable_slots,
    generate_slot_start_options,
    generate_time_options,
    parse_hm,
)
from campus.services.acl import can_edit_candidate, is_admin, module_writable_for
from campus.services.audit import add_log
from campus.services.candidates import find_candidate_by_phone, normalize_candidate_phone
from campus.services.interviews import (
    InterviewError,
    book_interview,
    calendar_payload,
    cancel_booking,
    create_availability,
    delete_availability,
    get_availability,
    interview_cfg,
    list_availability,
    validate_availability_no_overlap,
    validate_interview_type,
)
from campus.services.users import lookup_employee_for_registration
from campus.web.guards import login_required

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
    row = find_candidate_by_phone(get_db(), phone)
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
    rows = list_availability(
        get_db(), itype,
        date_from=request.args.get("from", ""),
        date_to=request.args.get("to", ""),
        user_id=request.args.get("user_id", type=int),
    )
    return jsonify(rows)


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
        for e in entries:
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


@bp.post("/api/interview/availability")
@login_required
def api_interview_availability_create():
    b = request.get_json(force=True)
    itype = b.get("type", "tech_interview")
    try:
        validate_interview_type(itype)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    entries, err = _parse_availability_entries(b, interview_cfg()["slot_minutes"])
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

    overlap_err = validate_availability_no_overlap(db, user_id, itype, entries, iv_name)
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    try:
        created = create_availability(db, user_id, itype, entries)
    except InterviewError as e:
        return jsonify({"error": str(e)}), e.status

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
    row = get_availability(db, aid)
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    if not _can_manage_availability(g.user, row["interview_type"], row["user_id"]):
        return jsonify({"error": "无权限删除该可面试时间"}), 403
    try:
        delete_availability(db, g.user, row)
    except InterviewError as e:
        return jsonify({"error": str(e)}), e.status
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
    slot_minutes = _slot_minutes_from_request(interview_cfg()["slot_minutes"])
    payload = calendar_payload(
        get_db(), itype, date_from, date_to,
        position=(request.args.get("position") or "").strip(),
        department=(request.args.get("department") or "").strip(),
        slot_minutes=slot_minutes,
    )
    return jsonify(payload)


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

    slot_minutes = _slot_minutes_from_request(interview_cfg()["slot_minutes"])
    try:
        book_interview(db, g.user, itype, cand, interviewer_id, start_at, slot_minutes)
    except InterviewError as e:
        return jsonify({"error": str(e)}), e.status
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
    cancel_booking(db, g.user, row, cand)
    db.commit()
    return jsonify({"ok": True})
