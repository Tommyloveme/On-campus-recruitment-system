# -*- coding: utf-8 -*-
"""面试日程相关常量与配置。"""
import json

INTERVIEW_TYPES = ("tech_interview", "manager_interview")


def interview_cfg():
    from campus.settings import load_app_config
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


def parse_job_roles(raw):
    """解析 users.job_roles JSON 为岗位列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return []


def interviewer_matches_position(job_roles, position):
    """岗位筛选：未选岗位则全部；面试官未配置岗位则视为可匹配任意岗位。"""
    if not position:
        return True
    if not job_roles:
        return True
    return position in job_roles
