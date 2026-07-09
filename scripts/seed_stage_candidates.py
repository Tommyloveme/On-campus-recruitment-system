# -*- coding: utf-8 -*-
"""为各流程阶段生成演示候选人（每阶段 10–20 人）。"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campus.core.stage_config import load_stages_meta
from campus.db.connection import DB_PATH, now_str
from campus.db.schema import init_db, migrate
from campus.domain.stage_routing import compute_current_stage

SURNAMES = "张李王刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文".strip()
GIVEN = "伟芳娜敏静丽强磊洋艳勇军杰娟涛明超秀英华慧建平刚桂兰".strip()
SCHOOLS = ["清华大学", "北京大学", "浙江大学", "上海交通大学", "南京大学", "华中科技大学", "武汉大学"]
MAJORS = ["计算机科学", "软件工程", "电子信息", "自动化", "通信工程", "数据科学"]
DEPTS = ["存储部", "计算部", "软件部", "网络部"]

BASE = {
    "education": "本科",
    "work_location": "深圳",
    "graduation_time": "2026-06-30",
}

#: 阶段由真实业务表存在的「当前环节」驱动（与 stage_rules.json 一致）。
#: Offer 策略子阶段（报批之后）按产品设计走手动流转（manual_stage 覆盖），
#: 且需主管面结果=通过。
STAGE_OVERRIDES = {
    "registration": {"current_step": ""},
    "resume_screening": {"current_step": "简历筛选"},
    "qualification": {"current_step": "资审"},
    "commercial_secret": {"current_step": "商业秘密签署"},
    "written_test": {"current_step": "笔试", "written_test_status": "已预约"},
    "personality_test": {"current_step": "性格测评",
                         "written_test_status": "已完成"},
    "qualification_interview": {"current_step": "资格面试",
                                "written_test_status": "已完成",
                                "personality_test_status": "已完成"},
    "tech_interview": {"current_step": "技术面",
                       "written_test_status": "已完成",
                       "personality_test_status": "已完成"},
    "manager_interview": {"current_step": "主管面",
                          "written_test_status": "已完成",
                          "personality_test_status": "已完成",
                          "tech_interview_result": "通过"},
    "approval": {"current_step": "报批",
                 "tech_interview_result": "通过",
                 "manager_interview_result": "通过"},
    "salary": {"current_step": "报批", "manual_stage": "salary",
               "tech_interview_result": "通过",
               "manager_interview_result": "通过"},
    "offer": {"current_step": "报批", "manual_stage": "offer",
              "tech_interview_result": "通过",
              "manager_interview_result": "通过"},
    "contract_signing": {"current_step": "报批", "manual_stage": "contract_signing",
                         "tech_interview_result": "通过",
                         "manager_interview_result": "通过"},
    "onboarding": {"current_step": "报批", "manual_stage": "onboarding",
                   "tech_interview_result": "通过",
                   "manager_interview_result": "通过",
                   "expected_onboard_time": "2026-07-15"},
}


def _rand_name():
    return random.choice(SURNAMES) + random.choice(GIVEN) + random.choice(GIVEN)


def _rand_phone(seq):
    return f"139{seq:08d}"[-11:]


def build_candidate(stage_key, seq):
    data = dict(BASE)
    data.update(STAGE_OVERRIDES.get(stage_key, {}))
    data["name"] = _rand_name()
    data["phone"] = _rand_phone(seq)
    data["resume_id"] = f"DEMO{seq:06d}"
    data["school"] = random.choice(SCHOOLS)
    data["major"] = random.choice(MAJORS)
    data["dept_level3"] = random.choice(DEPTS)
    data["interface_person"] = "hr01"
    data["sourcer"] = "lead01"
    stage = compute_current_stage(data)
    if stage != stage_key:
        data["current_stage"] = stage_key
    return data


def seed_stage_candidates(db, per_stage=15, prefix="DEMO", clear=False):
    if clear:
        db.execute("DELETE FROM candidates WHERE json_extract(data, '$.resume_id') LIKE ?", (f"{prefix}%",))
    stages = [s["key"] for s in load_stages_meta()]
    seq = int(db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(json_extract(data, '$.resume_id'), 5) AS INTEGER)), 0) AS m "
        "FROM candidates WHERE json_extract(data, '$.resume_id') LIKE ?",
        (f"{prefix}%",),
    ).fetchone()["m"])
    inserted = 0
    now = now_str()
    for stage_key in stages:
        n = random.randint(max(10, per_stage - 5), min(20, per_stage + 5))
        for _ in range(n):
            seq += 1
            data = build_candidate(stage_key, seq)
            data["resume_id"] = f"{prefix}{seq:06d}"
            compute_current_stage(data)
            db.execute(
                "INSERT INTO candidates (group_id, data, phone, created_at, updated_at) VALUES (?,?,?,?,?)",
                (None, json.dumps(data, ensure_ascii=False), data.get("phone"), now, now),
            )
            inserted += 1
    db.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="为各流程阶段生成演示候选人")
    parser.add_argument("--per-stage", type=int, default=15, help="每阶段目标人数（实际 10–20 随机）")
    parser.add_argument("--clear", action="store_true", help="清除 DEMO 前缀的演示候选人后重建")
    parser.add_argument("--init-db", action="store_true", help="若数据库不存在则初始化")
    args = parser.parse_args()
    if args.init_db or not os.path.exists(DB_PATH):
        init_db()
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    migrate(db)
    n = seed_stage_candidates(db, per_stage=args.per_stage, clear=args.clear)
    db.close()
    print(f"已写入 {n} 名演示候选人（各流程约 10–20 人）。")


if __name__ == "__main__":
    main()
