# -*- coding: utf-8 -*-
"""数据看板：各流程人数与通过率统计、全局总览数据组装。"""
from campus.core.stage_config import load_stages_meta
from campus.domain.stage_routing import stage_label_map

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


def build_overview_payload(db):
    """全局总览：全部候选人 + 最新进展 + 关键统计 + 看板数据。"""
    from campus.services.candidates import candidate_dict

    rows = db.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    cands = []
    stats = {"total": len(rows), "signed": 0, "onboarded": 0, "high_risk": 0}
    for r in rows:
        c = candidate_dict(r)
        log_row = db.execute(
            "SELECT message, created_at FROM logs WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (r["id"],)
        ).fetchone()
        c["latest_log"] = (f"[{log_row['created_at']}] {log_row['message']}" if log_row else "暂无更新记录")
        cands.append(c)
        d = c["data"]
        if d.get("sign_status") == "已签约":
            stats["signed"] += 1
        if d.get("onboarded") == "是":
            stats["onboarded"] += 1
        if d.get("onboard_risk") == "高":
            stats["high_risk"] += 1
    return [{
        "group_id": None,
        "group_name": "全部候选人",
        "stats": stats,
        "dashboard": compute_dashboard_stats(cands),
        "candidates": cands,
    }]
