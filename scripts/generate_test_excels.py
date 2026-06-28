# -*- coding: utf-8 -*-
"""生成 tests/test_excels 下的主数据表测试 Excel（含冗余列）。"""
import os
import random
from datetime import date, timedelta

from openpyxl import Workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "tests", "test_excels")

# 已映射列 + 冗余列（不在 field_mappings.json 中，导入时按表头拼音自动入库）
APP_HEADERS = [
    "简历编号", "候选人", "电话", "学历", "毕业院校", "专业",
    "二层部门", "三层部门",
    "拓源人", "拓源人部门", "接口人", "接口人部门",
    "来源渠道", "拟录取工作地",
    "登记状态", "简历筛选状态", "资审状态", "笔试状态",
    "技术面状态", "主管面状态", "报批状态", "谈薪状态",
    "Offer状态", "签约状态", "是否入职",
    # 冗余列
    "HR内部编号", "备注说明", "投递渠道明细", "校招批次",
]

MGMT_HEADERS = [
    "简历编号",
    "技术面结果", "主管面结果", "Offer发放时间", "预计入职时间", "入职风险", "当前进展",
    # 冗余列
    "跟进人", "管理备注", "二次确认状态",
]

SURNAMES = ["张", "王", "李", "赵", "陈", "刘", "杨", "黄", "周", "吴"]
GIVEN = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "勇"]
SCHOOLS = ["清华大学", "北京大学", "浙江大学", "复旦大学", "上海交通大学"]
MAJORS = ["计算机科学", "软件工程", "电子信息", "通信工程", "数据科学"]
EDUCATIONS = ["本科", "硕士", "博士"]
DEPT_L2 = ["存储部", "计算部", "网络部", "软件部"]
DEPT_L3 = ["块存储", "对象存储", "通用计算", "研发一组"]
LOCATIONS = ["深圳", "北京", "上海", "杭州", "成都"]
SOURCES = ["校园宣讲", "线上投递", "内推", "熟人推荐"]


def _app_row(
    resume_id, name, phone, education, school, major,
    dept_l2=None, dept_l3=None, sourcer="hr01", iface="hr02",
    reg_status="已登记", offer="未发放", sign="未签约", onboarded="否",
    hr_code="", note="", channel_detail="", batch="2026春招",
):
    dept_l2 = dept_l2 or random.choice(DEPT_L2)
    dept_l3 = dept_l3 or random.choice(DEPT_L3)
    return [
        resume_id, name, phone, education, school, major,
        dept_l2, dept_l3,
        sourcer, "软件部", iface, "软件部",
        random.choice(SOURCES), random.choice(LOCATIONS),
        reg_status, "通过", "通过", "已完成",
        "已完成", "已完成", "审批中", "谈薪中",
        offer, sign, onboarded,
        hr_code or f"HR-{resume_id[-4:]}",
        note or f"{name}样例备注",
        channel_detail or "官网+宣讲会",
        batch,
    ]


def _mgmt_row(
    resume_id, tech_result="通过", mgr_result="通过",
    offer_time=None, onboard_time=None, risk="中", progress="",
    follower="hr01", mgmt_note="", reconfirm="已确认",
):
    base = date(2026, 6, 1)
    offer_time = offer_time or (base + timedelta(days=random.randint(10, 40))).isoformat()
    onboard_time = onboard_time or (base + timedelta(days=random.randint(60, 120))).isoformat()
    return [
        resume_id,
        tech_result, mgr_result, offer_time, onboard_time, risk,
        progress or f"{date.today().strftime('%m%d')}跟进中",
        follower, mgmt_note or "管理侧冗余备注", reconfirm,
    ]


def build_application_rows():
    rows = [
        _app_row("RS2026001", "主表新人", "13790001001", "硕士", "测试大学", "软件工程",
                 dept_l2="软件部", dept_l3="研发一组", hr_code="HR-9001", note="冒烟测试固定行"),
        _app_row("RS2026002", "测试员", "13911112222", "本科", "测试大学", "计算机",
                 dept_l2="存储部", dept_l3="块存储", hr_code="HR-9002"),
    ]
    random.seed(2026)
    for i in range(3, 13):
        rid = f"RS2026{i:04d}"
        name = random.choice(SURNAMES) + random.choice(GIVEN)
        phone = f"138{random.randint(10000000, 99999999)}"
        rows.append(_app_row(
            rid, name, phone,
            random.choice(EDUCATIONS), random.choice(SCHOOLS), random.choice(MAJORS),
        ))
    return rows


def build_mgmt_rows():
    return [
        _mgmt_row("RS2026001", progress="0619主表新人进展", risk="低", mgmt_note="新人管理备注"),
        _mgmt_row("RS2026002", progress="0619测试员进展", risk="高", mgmt_note="测试员冗余字段"),
        _mgmt_row("RS2026003", progress="0619批量样例", risk="中"),
    ]


def write_workbook(path, sheet_name, headers, data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in data_rows:
        ws.append(row)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    return len(data_rows)


def main():
    app_path = os.path.join(OUT_DIR, "Application_sample.xlsx")
    mgmt_path = os.path.join(OUT_DIR, "候选人管理_sample.xlsx")

    app_n = write_workbook(app_path, "Sheet", APP_HEADERS, build_application_rows())
    mgmt_n = write_workbook(mgmt_path, "Sheet", MGMT_HEADERS, build_mgmt_rows())

    print(f"已写入 {app_path}（{app_n} 条，含冗余列：HR内部编号、备注说明、投递渠道明细、校招批次）")
    print(f"已写入 {mgmt_path}（{mgmt_n} 条，含冗余列：跟进人、管理备注、二次确认状态）")


if __name__ == "__main__":
    main()
