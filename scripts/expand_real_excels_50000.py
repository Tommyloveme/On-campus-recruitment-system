# -*- coding: utf-8 -*-
"""扩充 tests/fixtures/master_import 真实双 Excel 到至少 50000 条数据行（压测用）。

目标文件：
- tests/fixtures/master_import/applicationProcessList20260626083908.xlsx
- tests/fixtures/master_import/候选人面试安排管理列表20260626083900.xlsx

按「应聘档案编号」upsert 固定 TARGET_ROWS 条扩展候选人，重复运行不会重复追加。
使用 write_only 流式写出，避免 5 万行时内存暴涨。
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master_import"
APP = FIXTURES / "applicationProcessList20260626083908.xlsx"
INTERVIEW = FIXTURES / "候选人面试安排管理列表20260626083900.xlsx"
TARGET_ROWS = 50000

STAGES = [
    ("投递", "待投递", "", "", "", "", "", "", "", "", ""),
    ("简历筛选", "已登记", "待筛选", "", "", "", "", "", "", "", ""),
    ("资格审查", "已登记", "通过", "待审查", "待签署", "", "资审", "", "", "", ""),
    ("商业秘密签署", "已登记", "通过", "通过", "待签署", "待预约", "商业秘密签署", "", "", "", ""),
    ("笔试", "已登记", "通过", "通过", "已签署", "已预约", "笔试", "", "", "", ""),
    ("性格测评", "已登记", "通过", "通过", "已签署", "已完成", "性格测评", "", "", "", ""),
    ("资格面试", "已登记", "通过", "通过", "已签署", "已完成", "资格面试", "", "", "", ""),
    ("技术面", "已登记", "通过", "通过", "已签署", "已完成", "技术面", "已预约", "", "", ""),
    ("主管面", "已登记", "通过", "通过", "已签署", "已完成", "主管面", "已完成", "已预约", "", ""),
    ("offer策略", "已登记", "通过", "通过", "已签署", "已完成", "报批", "已完成", "已完成", "审批中", "待谈薪"),
]


def archive_id(seq: int) -> str:
    return f"SR20260709{seq:05d}"


def case_for(seq: int) -> dict:
    label, reg, resume, qual, secret, written, step, tech, manager, approval, salary = STAGES[(seq - 1) % len(STAGES)]
    return {
        "seq": seq,
        "aid": archive_id(seq),
        "label": label,
        "name": f"扩展候选人{seq:05d}-{label}",
        "phone": f"1378{seq:07d}"[-11:],
        "registration": reg,
        "resume": resume,
        "qualification": qual,
        "secret": secret,
        "written": written,
        "step": step,
        "tech": tech,
        "manager": manager,
        "approval": approval,
        "salary": salary,
    }


def read_headers(path: Path) -> list:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
        return [c if c is not None else "" for c in row]
    finally:
        wb.close()


def header_index(headers: list) -> dict:
    return {str(h).strip(): i for i, h in enumerate(headers) if h is not None and str(h).strip()}


def set_by_names(row: list, hm: dict, names, value):
    for name in names:
        if name in hm:
            row[hm[name]] = value


def build_application_row(headers: list, hm: dict, case: dict) -> list:
    row = [""] * len(headers)
    set_by_names(row, hm, ["应聘档案编号"], case["aid"])
    set_by_names(row, hm, ["简历编号"], "")
    set_by_names(row, hm, ["姓名", "候选人", "候选人姓名"], case["name"])
    set_by_names(row, hm, ["联系电话", "电话", "候选人手机号"], case["phone"])
    set_by_names(row, hm, ["学历", "学历（1）"], "硕士")
    set_by_names(row, hm, ["毕业学校（1）", "毕业院校", "学校"], "测试大学")
    set_by_names(row, hm, ["专业（1）", "专业"], "软件工程")
    set_by_names(row, hm, ["登记状态", "应聘状态"], case["registration"])
    set_by_names(row, hm, ["简历筛选状态"], case["resume"])
    set_by_names(row, hm, ["资审状态"], case["qualification"])
    set_by_names(row, hm, ["商业秘密签署状态", "商业合规签署通知状态", "保密协议状态"], case["secret"])
    set_by_names(row, hm, ["笔试状态", "考试状态"], case["written"])
    set_by_names(row, hm, ["当前环节"], case["step"])
    set_by_names(row, hm, ["当前环节状态"], "进行中" if case["step"] else "")
    set_by_names(row, hm, ["技术面状态", "专业面试状态"], case["tech"])
    set_by_names(row, hm, ["主管面状态", "业务主管面试状态"], case["manager"])
    set_by_names(row, hm, ["报批状态"], case["approval"])
    set_by_names(row, hm, ["谈薪状态"], case["salary"])
    set_by_names(row, hm, ["Offer状态"], "未发放" if case["label"] == "offer策略" else "")
    set_by_names(row, hm, ["签约状态"], "未签约")
    set_by_names(row, hm, ["是否入职"], "否")
    set_by_names(row, hm, ["二层部门", "录用二级部门"], "软件部")
    set_by_names(row, hm, ["三层部门", "录用三级部门"], "研发一组")
    set_by_names(row, hm, ["拓源人"], "hr01")
    set_by_names(row, hm, ["拓源人信息", "拓源人部门"], "软件部")
    set_by_names(row, hm, ["接口人"], "hr02")
    set_by_names(row, hm, ["接口人信息", "接口人部门"], "软件部")
    set_by_names(row, hm, ["备注说明"], f"{case['label']}流程扩展测试")
    return row


def build_interview_row(headers: list, hm: dict, case: dict) -> list:
    row = [""] * len(headers)
    set_by_names(row, hm, ["应聘档案编号"], case["aid"])
    set_by_names(row, hm, ["候选人编号"], case["aid"])
    set_by_names(row, hm, ["候选人姓名"], case["name"])
    set_by_names(row, hm, ["候选人手机号"], "+86 XXXXXXXXXXX")
    set_by_names(row, hm, ["当前环节"], case["step"])
    set_by_names(row, hm, ["当前环节状态"], "进行中" if case["step"] else "")
    set_by_names(row, hm, ["面试进展"], case["step"])
    set_by_names(row, hm, ["面试考核状态"], "考核中" if case["seq"] % 10 >= 6 else "")
    set_by_names(row, hm, ["综测状态"], "通过" if case["label"] in ("性格测评", "资格面试", "技术面", "主管面", "offer策略") else "")
    set_by_names(row, hm, ["考试状态"], case["written"])
    set_by_names(row, hm, ["专业面试-面试结论", "专业面试1-面试结论"], "A" if case["label"] in ("技术面", "主管面", "offer策略") else "")
    set_by_names(row, hm, ["业务主管面试-面试结论"], "通过" if case["label"] in ("主管面", "offer策略") else "")
    set_by_names(row, hm, ["面试结论"], "A" if case["label"] in ("技术面", "主管面", "offer策略") else "")
    return row


def expand_streaming(path: Path, builder, sheet_title: str = "Sheet") -> None:
    if not path.exists():
        raise FileNotFoundError(f"模板不存在: {path}")
    headers = read_headers(path)
    hm = header_index(headers)
    tmp = path.with_suffix(path.suffix + ".tmp")
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet_title)
    ws.append(headers)
    for seq in range(1, TARGET_ROWS + 1):
        case = case_for(seq)
        ws.append(builder(headers, hm, case))
        if seq % 10000 == 0:
            print(f"  … {path.name}: {seq}/{TARGET_ROWS}")
    wb.save(tmp)
    tmp.replace(path)
    print(f"{path.name}: data_rows={TARGET_ROWS}, cols={len(headers)}, sheet={sheet_title}")


def main():
    print(f"Expanding fixtures to {TARGET_ROWS} rows …")
    expand_streaming(APP, build_application_row, "Sheet")
    expand_streaming(INTERVIEW, build_interview_row, "Sheet1")
    print("done.")


if __name__ == "__main__":
    main()
