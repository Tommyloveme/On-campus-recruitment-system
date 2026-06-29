# -*- coding: utf-8 -*-
"""数据看板：各流程人数与通过率统计。"""
from campus.config_loader import load_stages_meta
from campus.stage_routing import stage_label_map

# 各流程用于计算通过率的状态字段与「通过」取值
STAGE_PASS_CONFIG = {
    "resume_screening": {
        "status_key": "resume_screening_status",
        "pass_values": {"通过"},
        "fail_values": {"不通过", "淘汰"},
        "pending_prefixes": ("待",),
    },
    "qualification": {
        "status_key": "qualification_status",
        "pass_values": {"通过"},
        "fail_values": {"不通过"},
        "pending_prefixes": ("待",),
    },
    "written_test": {
        "status_key": "written_test_status",
        "pass_values": {"已完成"},
        "fail_values": {"缺考", "放弃"},
        "pending_prefixes": ("待",),
    },
    "personality_test": {
        "status_key": "personality_test_status",
        "pass_values": {"已完成"},
        "fail_values": {"放弃"},
        "pending_prefixes": ("待",),
    },
    "qualification_interview": {
        "status_key": "qualification_interview_status",
        "pass_values": {"已完成"},
        "fail_values": {"放弃"},
        "pending_prefixes": ("待",),
    },
    "tech_interview": {
        "status_key": "tech_interview_result",
        "pass_values": {"通过"},
        "fail_values": {"不通过"},
        "pending_prefixes": ("待",),
    },
    "manager_interview": {
        "status_key": "manager_interview_result",
        "pass_values": {"通过"},
        "fail_values": {"不通过"},
        "pending_prefixes": ("待",),
    },
    "approval": {
        "status_key": "approval_status",
        "pass_values": {"已通过"},
        "fail_values": {"已驳回", "不通过"},
        "pending_prefixes": ("待", "审批"),
    },
    "salary": {
        "status_key": "salary_status",
        "pass_values": {"已接受"},
        "fail_values": {"已拒绝"},
        "pending_prefixes": ("待", "谈薪"),
    },
    "offer": {
        "status_key": "offer_status",
        "pass_values": {"已接受"},
        "fail_values": {"已拒绝", "已放弃"},
        "pending_prefixes": ("未", "待"),
    },
    "contract_signing": {
        "status_key": "contract_signing_status",
        "pass_values": {"已签约"},
        "fail_values": {"放弃签约"},
        "pending_prefixes": ("待", "签约中"),
    },
    "onboarding": {
        "status_key": "onboarded",
        "pass_values": {"是"},
        "fail_values": set(),
        "pending_prefixes": ("否",),
    },
}


def _classify_status(value, cfg):
    v = str(value or "").strip()
    if not v:
        return "none"
    if v in cfg.get("pass_values", set()):
        return "pass"
    if v in cfg.get("fail_values", set()):
        return "fail"
    for p in cfg.get("pending_prefixes", ()):
        if v.startswith(p):
            return "pending"
    return "other"


def compute_dashboard_stats(candidates):
    """candidates: list of dict with 'data' key."""
    labels = stage_label_map()
    stage_counts = {s["key"]: 0 for s in load_stages_meta()}
    stage_counts["unknown"] = 0

    pass_stats = {k: {"entered": 0, "passed": 0, "failed": 0, "pending": 0} for k in STAGE_PASS_CONFIG}

    for c in candidates:
        d = c.get("data") or {}
        stage = (d.get("current_stage") or "registration").strip()
        if stage in stage_counts:
            stage_counts[stage] += 1
        else:
            stage_counts["unknown"] += 1

        for sk, cfg in STAGE_PASS_CONFIG.items():
            status_key = cfg["status_key"]
            cls = _classify_status(d.get(status_key), cfg)
            if cls == "none":
                continue
            pass_stats[sk]["entered"] += 1
            if cls == "pass":
                pass_stats[sk]["passed"] += 1
            elif cls == "fail":
                pass_stats[sk]["failed"] += 1
            elif cls == "pending":
                pass_stats[sk]["pending"] += 1

    stage_count_list = []
    for s in load_stages_meta():
        key = s["key"]
        stage_count_list.append({
            "key": key,
            "label": labels.get(key, s["label"]),
            "short_label": s.get("short_label") or labels.get(key, key),
            "count": stage_counts.get(key, 0),
        })

    pass_rate_list = []
    for s in load_stages_meta():
        key = s["key"]
        if key not in STAGE_PASS_CONFIG:
            continue
        st = pass_stats[key]
        decided = st["passed"] + st["failed"]
        rate = round(st["passed"] / decided, 4) if decided else None
        pass_rate_list.append({
            "key": key,
            "label": labels.get(key, s["label"]),
            "entered": st["entered"],
            "passed": st["passed"],
            "failed": st["failed"],
            "pending": st["pending"],
            "rate": rate,
            "rate_pct": round(rate * 100, 1) if rate is not None else None,
        })

    return {
        "stage_counts": stage_count_list,
        "pass_rates": pass_rate_list,
        "by_stage": stage_counts,
    }
