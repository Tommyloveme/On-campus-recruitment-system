# -*- coding: utf-8 -*-
"""生成 tests/fixtures/master_import 下的主数据表测试 Excel（冒烟/单元测试共用）。

- Application_test.xlsx：applicationProcessList 风格主表（含冗余列，自动入库）；
- 候选人面试安排管理列表_test.xlsx：面试安排管理表（按应聘档案编号关联）。

简历编号统一为 SR+YYYYMMDD+序号 格式（如 SR20260101001），其中日期段即投递时间。
"""
import os
import random

from openpyxl import Workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "tests", "fixtures", "master_import")

APP_HEADERS = [
    "简历编号", "应聘档案编号", "候选人", "电话", "学历", "毕业院校", "专业",
    "二层部门", "三层部门",
    "拓源人", "拓源人部门", "接口人", "接口人部门",
    "来源渠道", "拟录取工作地",
    "登记状态", "简历筛选状态", "资审状态", "笔试状态",
    "技术面状态", "主管面状态", "报批状态", "谈薪状态",
    "Offer状态", "签约状态", "是否入职",
    "当前进展", "入职风险",
    # 冗余列（未映射，按表头原文自动入库）
    "HR内部编号", "备注说明", "投递渠道明细", "校招批次",
]

INTERVIEW_HEADERS = [
    "应聘档案编号", "候选人编号", "候选人姓名", "候选人手机号",
    "面试进展", "面试考核状态", "综测状态", "考试状态",
    "专业面试-面试结论", "业务主管面试-面试结论", "面试结论",
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


def sr_id(date_str, seq):
    """SR + YYYYMMDD + 3位序号，如 SR20260101001（日期段即投递时间）。"""
    return f"SR{date_str}{seq:03d}"


def _app_row(
    resume_id, name, phone, education, school, major,
    dept_l2=None, dept_l3=None, sourcer="hr01", iface="hr02",
    reg_status="已登记", offer="未发放", sign="未签约", onboarded="否",
    progress="", risk="中", hr_code="", note="",
):
    dept_l2 = dept_l2 or random.choice(DEPT_L2)
    dept_l3 = dept_l3 or random.choice(DEPT_L3)
    return [
        resume_id, resume_id, name, phone, education, school, major,
        dept_l2, dept_l3,
        sourcer, "软件部", iface, "软件部",
        random.choice(SOURCES), random.choice(LOCATIONS),
        reg_status, "通过", "通过", "已完成",
        "已完成", "已完成", "审批中", "谈薪中",
        offer, sign, onboarded,
        progress, risk,
        hr_code or f"HR-{resume_id[-4:]}",
        note or f"{name}样例备注",
        "官网+宣讲会",
        "2026春招",
    ]


def build_application_rows():
    rows = [
        _app_row(sr_id("20260101", 1), "主表新人", "13790001001", "硕士", "测试大学", "软件工程",
                 dept_l2="软件部", dept_l3="研发一组",
                 progress="0619主表新人进展", risk="低", hr_code="HR-9001", note="冒烟测试固定行"),
        _app_row(sr_id("20260102", 2), "测试员", "13911112222", "本科", "测试大学", "计算机",
                 dept_l2="存储部", dept_l3="块存储",
                 progress="0619测试员进展", risk="高", hr_code="HR-9002"),
    ]
    random.seed(2026)
    for i in range(3, 31):
        rid = sr_id("20260110", i)
        name = random.choice(SURNAMES) + random.choice(GIVEN) + random.choice(GIVEN)
        phone = f"138{random.randint(10000000, 99999999)}"
        rows.append(_app_row(
            rid, name, phone,
            random.choice(EDUCATIONS), random.choice(SCHOOLS), random.choice(MAJORS),
        ))
    return rows


def build_interview_rows():
    return [
        # 与主表按应聘档案编号关联；手机号为掩码，验证不参与唯一化
        [sr_id("20260101", 1), sr_id("20260101", 1), "主表新人", "+86 XXXXXXXXXXX",
         "综合测评-考试-专业面试", "面试通过", "通过", "已完成", "A", "", "A"],
        [sr_id("20260102", 2), sr_id("20260102", 2), "测试员", "+86 XXXXXXXXXXX",
         "综合测评-考试", "考核中", "通过", "已完成", "", "", ""],
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
    app_path = os.path.join(OUT_DIR, "Application_test.xlsx")
    iv_path = os.path.join(OUT_DIR, "候选人面试安排管理列表_test.xlsx")
    app_n = write_workbook(app_path, "Sheet", APP_HEADERS, build_application_rows())
    iv_n = write_workbook(iv_path, "Sheet1", INTERVIEW_HEADERS, build_interview_rows())
    print(f"已写入 {app_path}（{app_n} 条）")
    print(f"已写入 {iv_path}（{iv_n} 条）")


if __name__ == "__main__":
    main()
