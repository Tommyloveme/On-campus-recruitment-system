# -*- coding: utf-8 -*-
"""面试日程相关常量与配置。"""

INTERVIEW_TYPES = ("tech_interview", "manager_interview")


def interview_cfg():
    from campus.settings import load_app_config
    return load_app_config().get("interview", {
        "slot_minutes": 45,
        "time_step_minutes": 5,
        "day_start": "08:00",
        "day_end": "20:00",
    })


def validate_interview_type(t):
    if t not in INTERVIEW_TYPES:
        raise ValueError(f"未知面试类型: {t}")
    return t
