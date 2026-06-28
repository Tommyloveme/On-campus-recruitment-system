# -*- coding: utf-8 -*-
"""面试日程：可约时段生成与冲突检测。"""
from datetime import datetime, timedelta


def parse_hm(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m


def fmt_hm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def generate_time_options(day_start, day_end, step_minutes):
    """生成 step_minutes 间隔的时间选项（下拉/对齐用）。"""
    start = parse_hm(day_start)
    end = parse_hm(day_end)
    opts = []
    t = start
    while t <= end:
        opts.append(fmt_hm(t))
        t += step_minutes
    return opts


def generate_slot_start_options(day_start, day_end, slot_minutes):
    """按面试时长间隔生成可约开始时刻（如 45min → 08:00、08:45…）。"""
    start = parse_hm(day_start)
    end = parse_hm(day_end)
    opts = []
    t = start
    while t + slot_minutes <= end:
        opts.append(fmt_hm(t))
        t += slot_minutes
    return opts


def generate_bookable_slots(avail_date, start_time, end_time, slot_minutes, step_minutes):
    """
    从可面试起止时间生成 45 分钟可预约时段，起始对齐 step_minutes 网格。
    返回 [{"date","start","end","start_at","end_at"}, ...]
    """
    win_start = parse_hm(start_time)
    win_end = parse_hm(end_time)
    slots = []
    t = win_start
    while t + slot_minutes <= win_end:
        slots.append({
            "date": avail_date,
            "start": fmt_hm(t),
            "end": fmt_hm(t + slot_minutes),
            "start_at": f"{avail_date} {fmt_hm(t)}",
            "end_at": f"{avail_date} {fmt_hm(t + slot_minutes)}",
        })
        t += step_minutes
    return slots


def slots_overlap(a_start, a_end, b_start, b_end):
    """判断两个 HH:MM 时段是否重叠（端点相接不算重叠）。"""
    as_, ae = parse_hm(a_start), parse_hm(a_end)
    bs, be = parse_hm(b_start), parse_hm(b_end)
    return as_ < be and bs < ae


def find_overlapping_window(windows, avail_date, start_time, end_time):
    """在已有窗口列表中查找与 [start_time, end_time] 重叠的首条记录。"""
    for w in windows:
        if w.get("avail_date") != avail_date:
            continue
        if slots_overlap(start_time, end_time, w["start_time"], w["end_time"]):
            return w
    return None


def format_availability_window(avail_date, start_time, end_time):
    return f"{avail_date} {start_time}–{end_time}"


def expand_availability_windows(windows, slot_minutes, step_minutes, bookings_by_key):
    """
    windows: [{id, user_id, display_name, avail_date, start_time, end_time}, ...]
    bookings_by_key: {(user_id, start_at): booking_dict}
    返回带 booked 标记的 slot 列表。
    """
    result = []
    for w in windows:
        for slot in generate_bookable_slots(
                w["avail_date"], w["start_time"], w["end_time"], slot_minutes, step_minutes):
            key = (w["user_id"], slot["start_at"])
            booking = bookings_by_key.get(key)
            result.append({
                **slot,
                "availability_id": w["id"],
                "interviewer_id": w["user_id"],
                "interviewer_name": w["display_name"],
                "interviewer_dept": w.get("dept_level2") or w.get("department") or "",
                "job_roles": w.get("job_roles") or [],
                "booked": booking is not None,
                "booking": booking,
            })
    return result
