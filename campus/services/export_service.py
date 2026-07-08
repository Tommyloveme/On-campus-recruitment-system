# -*- coding: utf-8 -*-
"""可配置表格导出（config/export_profiles.json）。

导出列在后端 JSON 中配置，可卷积多张表的信息：
- candidates 预处理表字段（source=data，默认）；
- 系统派生字段（source=computed：当前流程、停留时长、SLA、最新进展）；
- data_hub 汇总总表字段（source=hub），各表按应聘档案编号→手机号唯一化关联。
"""
import json
import os
from functools import lru_cache

from campus.core.settings import BASE_DIR
from campus.db.field_store import field_get
from campus.domain.stage_routing import stage_label_map

EXPORT_PROFILES_PATH = os.path.join(BASE_DIR, "config", "export_profiles.json")

_SLA_LABEL = {"ok": "正常", "warn": "预警", "overdue": "超期"}


@lru_cache(maxsize=1)
def _load_profiles_cached(mtime):
    with open(EXPORT_PROFILES_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_export_profiles():
    if not os.path.isfile(EXPORT_PROFILES_PATH):
        return {"profiles": {}}
    return _load_profiles_cached(os.path.getmtime(EXPORT_PROFILES_PATH))


def get_export_profile(name):
    return (load_export_profiles().get("profiles") or {}).get(name)


def _hub_index(db, columns):
    """预取导出所需的 data_hub 值：{(resume_key, hub_source, field): value}。

    field 同时按字段键与中文列名索引，配置里写哪个都能命中。
    """
    sources = {c.get("hub_source") for c in columns if c.get("source") == "hub"}
    sources.discard(None)
    if not any(c.get("source") == "hub" for c in columns):
        return {}
    conds, args = [], []
    if sources:
        conds.append(f"source IN ({','.join('?' * len(sources))})")
        args.extend(sources)
    where = f" WHERE {' AND '.join(conds)}" if conds else ""
    idx = {}
    for r in db.execute(f"SELECT * FROM data_hub{where}", args).fetchall():
        for fkey in {r["field_key"], r["field_label"]}:
            if fkey:
                idx[(r["resume_id"], r["source"], fkey)] = r["value"]
    return idx


def _computed_value(key, row, data, ctx):
    stage = row["current_stage"] if "current_stage" in row.keys() else field_get(data, "current_stage")
    stage = stage or "registration"
    if key == "current_stage_label":
        return ctx["stage_labels"].get(stage, stage)
    if key == "stay_days":
        return (ctx["dwell"].get(row["id"]) or {}).get("days", "")
    if key == "sla_status":
        return _SLA_LABEL.get((ctx["dwell"].get(row["id"]) or {}).get("sla_status", ""), "")
    if key == "latest_log":
        r = ctx["db"].execute(
            "SELECT message, created_at FROM logs WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
            (row["id"],)).fetchone()
        return f"[{r['created_at']}] {r['message']}" if r else ""
    if key == "hub_key":
        return ctx["hub_key_fn"](data)
    return ""


def export_candidates_rows(db, rows, profile):
    """按导出方案生成 (headers, data_rows)。rows 为 candidates 表行。"""
    from campus.services.data_hub import hub_resume_key
    from campus.services.overview_stats import compute_stage_dwell

    columns = profile.get("columns") or []
    headers = [c.get("label") or c.get("key") or c.get("field") or "" for c in columns]

    needs_dwell = any(c.get("source") == "computed" and c.get("key") in ("stay_days", "sla_status")
                      for c in columns)
    dwell = compute_stage_dwell(db)[0] if needs_dwell else {}
    hub_idx = _hub_index(db, columns)
    ctx = {
        "db": db,
        "stage_labels": stage_label_map(),
        "dwell": dwell,
        "hub_key_fn": hub_resume_key,
    }

    out = []
    for row in rows:
        data = json.loads(row["data"])
        hub_key = hub_resume_key(data)
        line = []
        for c in columns:
            src = c.get("source") or "data"
            if src == "computed":
                line.append(_computed_value(c.get("key"), row, data, ctx))
            elif src == "hub":
                field = c.get("field") or c.get("key") or ""
                hs = c.get("hub_source")
                if hs:
                    line.append(hub_idx.get((hub_key, hs, field), ""))
                else:
                    v = ""
                    for s in ("master_import", "manual", "ui"):
                        v = hub_idx.get((hub_key, s, field), "")
                        if v:
                            break
                    line.append(v)
            else:
                line.append(field_get(data, c.get("key") or ""))
        out.append(line)
    return headers, out


def build_export_workbook(headers, data_rows, sheet_title="导出"):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31] or "导出"
    ws.append(headers)
    for line in data_rows:
        ws.append(["" if v is None else v for v in line])
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
            max(12, len(str(h)) * 2 + 4)
    return wb
