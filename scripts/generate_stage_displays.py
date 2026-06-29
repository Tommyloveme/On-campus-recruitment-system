# -*- coding: utf-8 -*-
"""根据各阶段 fields.json 生成 display.json（未列出字段默认不可见、不可编辑）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campus.config_loader import load_stages_meta

from campus.settings import BASE_DIR

STAGES_DIR = os.path.join(BASE_DIR, "config", "stages")
COMMON_KEYS = {"name", "phone", "resume_id"}

# 非登记阶段表格默认只展示姓名、电话 + 本阶段字段
FLOW_TABLE_IDENTITY = {"name": True, "phone": True, "resume_id": False}


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stage_field_defs(stage_key):
    path = os.path.join(STAGES_DIR, stage_key, "fields.json")
    if not os.path.exists(path):
        return []
    return _load_json(path).get("fields", [])


def build_display(stage_key):
    stage_fields = _stage_field_defs(stage_key)
    if stage_key == "registration":
        return None  # 保留手工配置

    visible = dict(FLOW_TABLE_IDENTITY)
    editable = {}
    column_order = ["name", "phone"]

    for f in stage_fields:
        k = f["key"]
        if f.get("visible", True):
            visible[k] = True
            column_order.append(k)
        if f.get("editable", False):
            editable[k] = True

    return {
        "comment": f"阶段「{stage_key}」界面配置：未在 visible/editable 中列出的字段默认不可见、不可编辑",
        "column_order": column_order,
        "frozen_column_count": 2,
        "visible": visible,
        "editable": editable,
    }


def main():
    for stage in load_stages_meta():
        key = stage["key"]
        if key == "registration":
            continue
        display = build_display(key)
        if not display:
            continue
        out = os.path.join(STAGES_DIR, key, "display.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(display, f, ensure_ascii=False, indent=2)
        print("wrote", out)


if __name__ == "__main__":
    main()
