# -*- coding: utf-8 -*-
"""生成 Application_test.xlsx（30 条样例，供主数据表导入测试）。"""
import os
import random

from openpyxl import Workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "fixtures", "master_import", "Application_test.xlsx")

HEADERS = [
    "简历编号", "候选人", "电话", "学历", "毕业院校", "专业",
    "二层部门", "三层部门", "登记状态", "简历筛选状态", "资审状态",
    "Offer状态", "签约状态", "是否入职",
]

SURNAMES = ["张", "王", "李", "赵", "陈", "刘", "杨", "黄", "周", "吴"]
GIVEN = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "勇", "杰", "婷", "浩", "超", "琳"]
SCHOOLS = ["清华大学", "北京大学", "浙江大学", "复旦大学", "上海交通大学", "南京大学", "武汉大学", "中山大学"]
MAJORS = ["计算机科学", "软件工程", "电子信息", "通信工程", "自动化", "数据科学", "人工智能"]
EDUCATIONS = ["本科", "硕士", "博士"]
DEPT_L2 = ["存储部", "计算部", "网络部", "软件部"]
DEPT_L3 = ["块存储", "对象存储", "通用计算", "研发一组"]


def row_fixed(i, resume_id, name, phone, education, school, major, risk_note=""):
    return [
        resume_id, name, phone, education, school, major,
        random.choice(DEPT_L2), random.choice(DEPT_L3),
        "已登记", "通过", "通过", "未发放", "未签约", "否",
    ]


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.append(HEADERS)

    # 与冒烟测试兼容的固定行
    ws.append(row_fixed(1, "RS2026001", "主表新人", f"13790001001", "硕士", "测试大学", "软件工程"))
    ws.append(row_fixed(2, "RS2026002", "测试员", "13911112222", "本科", "测试大学", "计算机"))

    random.seed(42)
    for i in range(3, 31):
        rid = f"RS2026{i:04d}"
        name = random.choice(SURNAMES) + random.choice(GIVEN) + random.choice(GIVEN)
        phone = f"138{random.randint(10000000, 99999999)}"
        edu = random.choice(EDUCATIONS)
        school = random.choice(SCHOOLS)
        major = random.choice(MAJORS)
        ws.append(row_fixed(i, rid, name, phone, edu, school, major))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb.save(OUT)
    print(f"已写入 {OUT}（{ws.max_row - 1} 条数据）")


if __name__ == "__main__":
    main()
