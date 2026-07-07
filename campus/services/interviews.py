# -*- coding: utf-8 -*-
"""面试日程业务：配置、可面试时段 CRUD、日历展开、预约/取消。

SQL 与业务规则集中于此；web 层（campus.web.interviews）只做参数解析、
权限校验与 JSON 组装。时段/重叠等纯算法在 campus.domain.interview_slots。
"""
import json
import sqlite3

from campus.core.settings import load_app_config
from campus.core.stage_config import get_stage_meta
from campus.db.connection import now_str
from campus.domain.employees import interviewer_matches_position, parse_job_roles
from campus.domain.interview_slots import (
    expand_availability_windows,
    find_overlapping_window,
    fmt_hm,
    format_availability_window,
    parse_hm,
)
from campus.domain.stage_routing import compute_current_stage
from campus.services.audit import add_log

INTERVIEW_TYPES = ("tech_interview", "manager_interview")


class InterviewError(Exception):
    """业务错误（附 HTTP 状态码），由 web 层转为 JSON 响应。"""

    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def interview_cfg():
    ic = load_app_config().get("interview", {})
    return {
        "slot_minutes": int(ic.get("slot_minutes", 45)),
        "time_step_minutes": int(ic.get("time_step_minutes", 5)),
        "day_start": ic.get("day_start", "08:00"),
        "day_end": ic.get("day_end", "20:00"),
        "position_options": list(ic.get("position_options") or ["软件岗", "测试岗", "算法岗"]),
    }


def validate_interview_type(t):
    if t not in INTERVIEW_TYPES:
        raise ValueError(f"未知面试类型: {t}")
    return t


# ---------------------------------------------------------------------------
# 可面试时段
# ---------------------------------------------------------------------------

def list_availability(db, itype, date_from="", date_to="", user_id=None):
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
    out = []
    for r in db.execute(sql, params).fetchall():
        d = dict(r)
        d["job_roles"] = parse_job_roles(d.get("job_roles"))
        out.append(d)
    return out


def validate_availability_no_overlap(db, user_id, itype, entries, iv_name):
    """校验新录入时段与同面试官已有/同批次时段不重叠；返回错误文案或 None。"""
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


def create_availability(db, user_id, itype, entries):
    """写入可面试时段，返回创建条数；时段撞唯一索引时抛 InterviewError(409)。"""
    created = 0
    for entry in entries:
        end_time = fmt_hm(parse_hm(entry["start_time"]) + entry["slot_minutes"])
        try:
            db.execute(
                "INSERT INTO interviewer_availability (user_id, interview_type, avail_date, start_time, end_time, group_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (user_id, itype, entry["date"], entry["start_time"], end_time, None, now_str()),
            )
            created += 1
        except sqlite3.IntegrityError:
            raise InterviewError("该时段已被他人录入，请刷新后重试", status=409)
    return created


def get_availability(db, aid):
    return db.execute("SELECT * FROM interviewer_availability WHERE id=?", (aid,)).fetchone()


def delete_availability(db, user, row):
    """删除可面试时段（调用方已做权限校验）；已有预约时抛错。"""
    booked = db.execute(
        "SELECT id FROM interview_bookings WHERE interviewer_id=? AND interview_type=? "
        "AND avail_date=? AND start_time=?",
        (row["user_id"], row["interview_type"], row["avail_date"], row["start_time"]),
    ).fetchone()
    if booked:
        raise InterviewError("该时段已有预约，请先取消预约后再删除")
    iv = db.execute("SELECT display_name FROM users WHERE id=?", (row["user_id"],)).fetchone()
    iv_name = iv["display_name"] if iv else str(row["user_id"])
    db.execute("DELETE FROM interviewer_availability WHERE id=?", (row["id"],))
    add_log(user, "update",
            f"{user['display_name']} 删除了面试官「{iv_name}」"
            f" {row['avail_date']} {row['start_time']} 的可面试时间（{row['interview_type']}）",
            module=row["interview_type"])


# ---------------------------------------------------------------------------
# 日历
# ---------------------------------------------------------------------------

def calendar_payload(db, itype, date_from, date_to, position, department, slot_minutes):
    ic = interview_cfg()
    sql = ("SELECT a.id, a.user_id, u.display_name, u.job_roles, u.dept_level2, u.department, "
           "a.avail_date, a.start_time, a.end_time "
           "FROM interviewer_availability a JOIN users u ON u.id=a.user_id "
           "WHERE a.interview_type=? AND a.avail_date>=? AND a.avail_date<=?")
    windows = []
    for r in db.execute(sql, [itype, date_from, date_to]).fetchall():
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

    return {
        "slots": slots,
        "config": {**ic, "slot_minutes": slot_minutes},
        "filter_options": {"departments": departments},
    }


# ---------------------------------------------------------------------------
# 预约 / 取消
# ---------------------------------------------------------------------------

def _stage_data_keys(itype):
    if itype == "tech_interview":
        return "tech_interview_status", "tech_interview_time", "tech_interviewer"
    return "manager_interview_status", "manager_interview_time", "manager_interviewer"


def book_interview(db, user, itype, cand, interviewer_id, start_at, slot_minutes):
    """预约面试：写 booking、同步候选人阶段字段并记日志（含事务与并发冲突处理）。"""
    parts = start_at.split(" ")
    if len(parts) != 2:
        raise InterviewError("start_at 格式应为 YYYY-MM-DD HH:MM")
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
            raise InterviewError("该时段已被预约，请刷新后重试", status=409)

        db.execute(
            "INSERT INTO interview_bookings (interview_type, interviewer_id, candidate_id, avail_date, "
            "start_time, end_time, start_at, booked_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (itype, interviewer_id, cand["id"], avail_date, start_time, end_time, start_at,
             user["id"], now_str()),
        )
        data = json.loads(cand["data"])
        status_key, time_key, interviewer_key = _stage_data_keys(itype)
        iv = db.execute("SELECT display_name FROM users WHERE id=?", (interviewer_id,)).fetchone()
        data[status_key] = "已预约"
        data[time_key] = start_at
        data[interviewer_key] = iv["display_name"] if iv else ""
        compute_current_stage(data)
        db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                   (json.dumps(data, ensure_ascii=False), now_str(), cand["id"]))

        cname = data.get("name", "")
        add_log(user, "update",
                f"{user['display_name']} 为「{cname}」（{data.get('phone', '')}）预约了 {start_at} 的"
                f"{get_stage_meta(itype)['label']}（面试官 {iv['display_name'] if iv else ''}）",
                cand["id"], cname, cand["group_id"], module=itype)
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise InterviewError("该时段已被他人预约，请刷新后重试", status=409)


def cancel_booking(db, user, booking, cand):
    """取消预约：删 booking、回退候选人阶段字段并记日志。"""
    itype = booking["interview_type"]
    data = json.loads(cand["data"])
    status_key, time_key, interviewer_key = _stage_data_keys(itype)
    cname = data.get("name", "")

    db.execute("DELETE FROM interview_bookings WHERE id=?", (booking["id"],))
    data[status_key] = "待预约"
    data[time_key] = ""
    data[interviewer_key] = ""
    compute_current_stage(data)
    db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
               (json.dumps(data, ensure_ascii=False), now_str(), cand["id"]))
    add_log(user, "update",
            f"{user['display_name']} 取消了「{cname}」的 {booking['start_at']} 面试预约（{get_stage_meta(itype)['label']}）",
            cand["id"], cname, cand["group_id"], module=itype)
