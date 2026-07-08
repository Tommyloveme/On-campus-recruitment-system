# -*- coding: utf-8 -*-
"""向根目录真实主数据双 Excel 写入流程状态测试样例。

按「应聘档案编号」upsert，重复运行不会重复追加。用于通过真实
applicationProcessList / 候选人面试安排管理列表 导入验证：
01-投递 到 10-offer策略。
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "applicationProcessList20260626083908.xlsx"
INTERVIEW_FILE = ROOT / "候选人面试安排管理列表20260626083900.xlsx"


def sr_id(date_str, seq):
    return f"SR{date_str}{seq:05d}"


CASES = [
    {
        "seq": 1, "date": "20260301", "name": "真实状态01投递", "phone": "13790003001",
        "registration": "待投递", "resume": "", "qualification": "", "secret": "",
        "written": "", "current_step": "", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "registration", "expected_status": "01-投递",
    },
    {
        "seq": 2, "date": "20260302", "name": "真实状态02简历筛选", "phone": "13790003002",
        "registration": "已登记", "resume": "待筛选", "qualification": "", "secret": "",
        "written": "", "current_step": "", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "resume_screening", "expected_status": "02-简历筛选",
    },
    {
        "seq": 3, "date": "20260303", "name": "真实状态03资格审查", "phone": "13790003003",
        "registration": "已登记", "resume": "通过", "qualification": "待审查", "secret": "待签署",
        "written": "", "current_step": "资审", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "qualification", "expected_status": "03-资格审查",
    },
    {
        "seq": 4, "date": "20260304", "name": "真实状态04商业秘密签署", "phone": "13790003004",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "待签署",
        "written": "待预约", "current_step": "商业秘密签署", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "commercial_secret", "expected_status": "04-商业秘密签署",
    },
    {
        "seq": 5, "date": "20260305", "name": "真实状态05笔试", "phone": "13790003005",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已预约", "current_step": "笔试", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "written_test", "expected_status": "05-笔试",
    },
    {
        "seq": 6, "date": "20260306", "name": "真实状态06性格测评", "phone": "13790003006",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已完成", "current_step": "性格测评", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "personality_test", "expected_status": "06-性格测评",
    },
    {
        "seq": 7, "date": "20260307", "name": "真实状态07资格面试", "phone": "13790003007",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已完成", "current_step": "资格面试", "tech": "", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "qualification_interview", "expected_status": "07-资格面试",
    },
    {
        "seq": 8, "date": "20260308", "name": "真实状态08技术面", "phone": "13790003008",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已完成", "current_step": "技术面", "tech": "已预约", "manager": "", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "tech_interview", "expected_status": "08-技术面",
    },
    {
        "seq": 9, "date": "20260309", "name": "真实状态09主管面", "phone": "13790003009",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已完成", "current_step": "主管面", "tech": "已完成", "manager": "已预约", "approval": "",
        "salary": "", "offer": "", "sign": "未签约", "onboarded": "否",
        "expected_stage": "manager_interview", "expected_status": "09-主管面",
    },
    {
        "seq": 10, "date": "20260310", "name": "真实状态10offer策略", "phone": "13790003010",
        "registration": "已登记", "resume": "通过", "qualification": "通过", "secret": "已签署",
        "written": "已完成", "current_step": "报批", "tech": "已完成", "manager": "已完成", "approval": "审批中",
        "salary": "待谈薪", "offer": "未发放", "sign": "未签约", "onboarded": "否",
        "expected_stage": "approval", "expected_status": "10-offer策略",
    },
]


def ensure_col(ws, header):
    headers = [c.value for c in ws[1]]
    if header in headers:
        return headers.index(header) + 1
    col = ws.max_column + 1
    ws.cell(row=1, column=col, value=header)
    return col


def upsert_row(ws, archive_id, values):
    key_col = ensure_col(ws, "应聘档案编号")
    row_idx = None
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row=row, column=key_col).value or "").strip() == archive_id:
            row_idx = row
            break
    if row_idx is None:
        row_idx = ws.max_row + 1
    for header, value in values.items():
        ws.cell(row=row_idx, column=ensure_col(ws, header), value=value)
    return row_idx


def app_values(case):
    rid = sr_id(case["date"], case["seq"])
    return {
        "应聘档案编号": rid,
        "简历编号": rid,
        "姓名": case["name"],
        "候选人": case["name"],
        "联系电话": case["phone"],
        "电话": case["phone"],
        "学历": "硕士",
        "毕业院校": "测试大学",
        "专业": "软件工程",
        "登记状态": case["registration"],
        "应聘状态": case["registration"],
        "简历筛选状态": case["resume"],
        "资审状态": case["qualification"],
        "商业秘密签署状态": case["secret"],
        "笔试状态": case["written"],
        "当前环节": case["current_step"],
        "当前环节状态": "进行中" if case["current_step"] else "",
        "技术面状态": case["tech"],
        "主管面状态": case["manager"],
        "报批状态": case["approval"],
        "谈薪状态": case["salary"],
        "Offer状态": case["offer"],
        "签约状态": case["sign"],
        "是否入职": case["onboarded"],
        "备注说明": f"{case['name']}流程状态测试",
    }


def interview_values(case):
    rid = sr_id(case["date"], case["seq"])
    return {
        "应聘档案编号": rid,
        "候选人编号": rid,
        "候选人姓名": case["name"],
        "候选人手机号": "+86 XXXXXXXXXXX",
        "当前环节": case["current_step"],
        "面试进展": case["current_step"],
        "考试状态": "已完成" if case["seq"] >= 5 else "",
        "综测状态": "通过" if case["seq"] >= 6 else "",
        "专业面试-面试结论": "A" if case["seq"] >= 8 else "",
        "业务主管面试-面试结论": "通过" if case["seq"] >= 9 else "",
        "面试结论": "A" if case["seq"] >= 8 else "",
    }


def expand():
    app_wb = load_workbook(APP_FILE)
    app_ws = app_wb.active
    interview_wb = load_workbook(INTERVIEW_FILE)
    interview_ws = interview_wb.active
    for case in CASES:
        rid = sr_id(case["date"], case["seq"])
        upsert_row(app_ws, rid, app_values(case))
        # 只给确实需要面试/环节表推动的流程补面试表，避免早期阶段被面试进展误命中。
        if case["seq"] >= 5:
            upsert_row(interview_ws, rid, interview_values(case))
    app_wb.save(APP_FILE)
    interview_wb.save(INTERVIEW_FILE)
    return len(CASES)


if __name__ == "__main__":
    print(f"已写入/更新真实流程状态样例 {expand()} 条")
