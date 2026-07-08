# -*- coding: utf-8 -*-
"""数据看板：各流程人数与通过率统计、全局总览数据组装。"""
from campus.core.stage_config import load_stages_meta
from campus.db.field_store import field_get
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
        stage = str(c.get("current_stage") or field_get(d, "current_stage")
                    or "registration").strip()
        if stage in stage_counts:
            stage_counts[stage] += 1
        else:
            stage_counts["unknown"] += 1

        for sk, cfg in STAGE_PASS_CONFIG.items():
            status_key = cfg["status_key"]
            cls = _classify_status(field_get(d, status_key), cfg)
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


def load_sla_config():
    """SLA 配置：各阶段目标停留天数（config/sla.json）。"""
    import json
    import os
    from campus.core.settings import BASE_DIR
    path = os.path.join(BASE_DIR, "config", "sla.json")
    default = {"warn_days": 5, "max_days": 10}
    if not os.path.isfile(path):
        return {"default": default, "stages": {}}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("default", default)
    cfg.setdefault("stages", {})
    return cfg


def _days_between(start_str, end_dt):
    from datetime import datetime
    s = str(start_str or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return max(0.0, (end_dt - datetime.strptime(s, fmt)).total_seconds() / 86400.0)
        except ValueError:
            continue
    return None


def compute_stage_dwell(db, sla_cfg=None):
    """各候选人当前阶段停留时长 + 各阶段 SLA 汇总。

    返回 (per_candidate, per_stage)：
    - per_candidate: {candidate_id: {stage, days, sla_status}}
    - per_stage: [{key, label, count, avg_days, max_days, warn, overdue, sla}]
    """
    from datetime import datetime
    sla_cfg = sla_cfg or load_sla_config()
    default_sla = sla_cfg.get("default") or {"warn_days": 5, "max_days": 10}
    now = datetime.now()
    labels = stage_label_map()

    entered = {}
    for r in db.execute(
        "SELECT candidate_id, stage, entered_at FROM candidate_stage_history "
        "ORDER BY candidate_id, id"
    ).fetchall():
        entered[r["candidate_id"]] = (r["stage"], r["entered_at"])

    per_candidate = {}
    agg = {}
    for r in db.execute("SELECT id, current_stage, updated_at, created_at FROM candidates").fetchall():
        stage = r["current_stage"] or "registration"
        hist = entered.get(r["id"])
        since = hist[1] if hist and hist[0] == stage else (r["updated_at"] or r["created_at"])
        days = _days_between(since, now)
        if days is None:
            days = 0.0
        sla = sla_cfg["stages"].get(stage) or default_sla
        if days > sla.get("max_days", 10):
            status = "overdue"
        elif days > sla.get("warn_days", 5):
            status = "warn"
        else:
            status = "ok"
        per_candidate[r["id"]] = {
            "stage": stage,
            "days": round(days, 1),
            "sla_status": status,
            "entered_at": since,
        }
        a = agg.setdefault(stage, {"count": 0, "total": 0.0, "max": 0.0, "warn": 0, "overdue": 0})
        a["count"] += 1
        a["total"] += days
        a["max"] = max(a["max"], days)
        if status == "warn":
            a["warn"] += 1
        elif status == "overdue":
            a["overdue"] += 1

    per_stage = []
    for s in load_stages_meta():
        key = s["key"]
        a = agg.get(key) or {"count": 0, "total": 0.0, "max": 0.0, "warn": 0, "overdue": 0}
        sla = sla_cfg["stages"].get(key) or default_sla
        per_stage.append({
            "key": key,
            "label": labels.get(key, s["label"]),
            "count": a["count"],
            "avg_days": round(a["total"] / a["count"], 1) if a["count"] else 0,
            "max_days": round(a["max"], 1),
            "warn": a["warn"],
            "overdue": a["overdue"],
            "sla": sla,
        })
    return per_candidate, per_stage


def build_overview_payload(db):
    """全局总览：全部候选人 + 最新进展 + 关键统计 + 看板数据 + SLA/停留时长。"""
    from campus.services.candidates import candidate_dict

    sla_cfg = load_sla_config()
    dwell_by_cand, dwell_by_stage = compute_stage_dwell(db, sla_cfg)

    rows = db.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    cands = []
    stats = {"total": len(rows), "signed": 0, "onboarded": 0, "high_risk": 0, "sla_overdue": 0}
    for r in rows:
        c = candidate_dict(r)
        log_row = db.execute(
            "SELECT message, created_at FROM logs WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (r["id"],)
        ).fetchone()
        c["latest_log"] = (f"[{log_row['created_at']}] {log_row['message']}" if log_row else "暂无更新记录")
        dw = dwell_by_cand.get(r["id"]) or {}
        c["stay_days"] = dw.get("days", 0)
        c["sla_status"] = dw.get("sla_status", "ok")
        c["stage_entered_at"] = dw.get("entered_at", "")
        cands.append(c)
        d = c["data"]
        if field_get(d, "sign_status") == "已签约":
            stats["signed"] += 1
        if field_get(d, "onboarded") == "是":
            stats["onboarded"] += 1
        if field_get(d, "onboard_risk") == "高":
            stats["high_risk"] += 1
        if c["sla_status"] == "overdue":
            stats["sla_overdue"] += 1
    return [{
        "group_id": None,
        "group_name": "全部候选人",
        "stats": stats,
        "dashboard": compute_dashboard_stats(cands),
        "stage_dwell": dwell_by_stage,
        "sla_config": sla_cfg,
        "candidates": cands,
    }]
