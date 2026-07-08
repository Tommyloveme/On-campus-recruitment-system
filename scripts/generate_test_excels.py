# -*- coding: utf-8 -*-
"""生成 tests/fixtures/master_import 下的主数据表测试 Excel（冒烟/单元测试共用）。

- Application_test.xlsx：applicationProcessList 风格主表（含冗余列，自动入库）；
- 候选人面试安排管理列表_test.xlsx：面试安排管理表（按应聘档案编号关联）。

应聘档案编号/简历编号统一为 SR+YYYYMMDD+5位序号（如 SR2025081100434），共15位，日期段即投递时间。
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
    "登记状态", "简历筛选状态", "资审状态", "商业秘密签署状态", "笔试状态",
    "技术面状态", "主管面状态", "报批状态", "谈薪状态",
    "Offer状态", "签约状态", "是否入职",
    "当前环节", "当前环节状态", "当前进展", "入职风险",
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
    """SR + YYYYMMDD + 5位序号，如 SR2025081100434（共15位；日期段即投递时间）。"""
    return f"SR{date_str}{seq:05d}"


def _app_row(
    resume_id, name, phone, education, school, major,
    dept_l2=None, dept_l3=None, sourcer="hr01", iface="hr02",
    reg_status="已登记", resume_screening="通过", qualification="通过",
    commercial_secret="已签署", written_test="已完成",
    tech_status="已完成", manager_status="已完成",
    approval="审批中", salary="谈薪中",
    offer="未发放", sign="未签约", onboarded="否",
    current_step="", current_step_status="", progress="", risk="中", hr_code="", note="",
):
    dept_l2 = dept_l2 or random.choice(DEPT_L2)
    dept_l3 = dept_l3 or random.choice(DEPT_L3)
    return [
        resume_id, resume_id, name, phone, education, school, major,
        dept_l2, dept_l3,
        sourcer, "软件部", iface, "软件部",
        random.choice(SOURCES), random.choice(LOCATIONS),
        reg_status, resume_screening, qualification, commercial_secret, written_test,
        tech_status, manager_status, approval, salary,
        offer, sign, onboarded,
        current_step, current_step_status, progress, risk,
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
    rows.extend(build_stage_status_rows())
    random.seed(2026)
    for i in range(20, 31):
        rid = sr_id("20260110", i)
        name = random.choice(SURNAMES) + random.choice(GIVEN) + random.choice(GIVEN)
        phone = f"138{random.randint(10000000, 99999999)}"
        rows.append(_app_row(
            rid, name, phone,
            random.choice(EDUCATIONS), random.choice(SCHOOLS), random.choice(MAJORS),
        ))
    return rows


def build_stage_status_rows():
    """覆盖 01-投递 到 10-offer策略 的流程状态 fixture。"""
    scenarios = [
        # name, date, seq, phone, registration, resume, qualification, secret, written, current_step, tech, manager, approval, salary, offer, sign, onboarded
        ("状态01投递", "20260201", 1, "13790002001", "待投递", "", "", "", "", "", "", "", "", "", "", "未签约", "否"),
        ("状态02简历筛选", "20260202", 2, "13790002002", "已登记", "待筛选", "", "", "", "", "", "", "", "", "", "未签约", "否"),
        ("状态03资格审查", "20260203", 3, "13790002003", "已登记", "通过", "待审查", "待签署", "", "资审", "", "", "", "", "", "未签约", "否"),
        ("状态04商业秘密签署", "20260204", 4, "13790002004", "已登记", "通过", "通过", "待签署", "待预约", "", "", "", "", "", "", "未签约", "否"),
        ("状态05笔试", "20260205", 5, "13790002005", "已登记", "通过", "通过", "已签署", "已预约", "笔试", "", "", "", "", "", "未签约", "否"),
        ("状态06性格测评", "20260206", 6, "13790002006", "已登记", "通过", "通过", "已签署", "已完成", "性格测评", "", "", "", "", "", "未签约", "否"),
        ("状态07资格面试", "20260207", 7, "13790002007", "已登记", "通过", "通过", "已签署", "已完成", "资格面试", "", "", "", "", "", "未签约", "否"),
        ("状态08技术面", "20260208", 8, "13790002008", "已登记", "通过", "通过", "已签署", "已完成", "技术面", "已预约", "", "", "", "", "未签约", "否"),
        ("状态09主管面", "20260209", 9, "13790002009", "已登记", "通过", "通过", "已签署", "已完成", "主管面", "已完成", "已预约", "", "", "", "未签约", "否"),
        ("状态10offer策略", "20260210", 10, "13790002010", "已登记", "通过", "通过", "已签署", "已完成", "报批", "已完成", "已完成", "审批中", "待谈薪", "未发放", "未签约", "否"),
    ]
    rows = []
    for name, date, seq, phone, reg, resume, qual, secret, written, progress, tech, manager, approval, salary, offer, sign, onboarded in scenarios:
        rows.append(_app_row(
            sr_id(date, seq), name, phone, "硕士", "测试大学", "软件工程",
            dept_l2="软件部", dept_l3="研发一组",
            reg_status=reg,
            resume_screening=resume,
            qualification=qual,
            commercial_secret=secret,
            written_test=written,
            tech_status=tech,
            manager_status=manager,
            approval=approval,
            salary=salary,
            offer=offer,
            sign=sign,
            onboarded=onboarded,
            current_step=progress,
            current_step_status="进行中" if progress else "",
            progress=f"{name}当前进展",
            risk="低",
            hr_code=f"HR-ST{seq:02d}",
            note=f"{name}流程状态测试",
        ))
    return rows


def build_interview_rows():
    rows = [
        # 与主表按应聘档案编号关联；手机号为掩码，验证不参与唯一化
        [sr_id("20260101", 1), sr_id("20260101", 1), "主表新人", "+86 XXXXXXXXXXX",
         "综合测评-考试-专业面试", "面试通过", "通过", "已完成", "A", "", "A"],
        [sr_id("20260102", 2), sr_id("20260102", 2), "测试员", "+86 XXXXXXXXXXX",
         "综合测评-考试", "考核中", "通过", "已完成", "", "", ""],
    ]
    interview_progress = {
        5: "笔试",
        6: "性格测评",
        7: "资格面试",
        8: "技术面",
        9: "主管面",
        10: "报批",
    }
    for seq in range(5, 11):
        rid = sr_id(f"202602{seq:02d}", seq)
        name = f"状态{seq:02d}{['投递','简历筛选','资格审查','商业秘密签署','笔试','性格测评','资格面试','技术面','主管面','offer策略'][seq-1]}"
        rows.append([
            rid, rid, name, "+86 XXXXXXXXXXX",
            interview_progress.get(seq, ""),
            "考核中" if seq >= 7 else "",
            "通过" if seq >= 6 else "",
            "已完成" if seq >= 5 else "",
            "A" if seq >= 8 else "",
            "通过" if seq >= 9 else "",
            "A" if seq >= 8 else "",
        ])
    return rows


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
