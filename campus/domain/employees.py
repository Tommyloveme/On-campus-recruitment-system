# -*- coding: utf-8 -*-
"""员工（用户）信息的纯函数：部门展示、部门拆分、岗位列表解析。

不访问数据库；入参为用户行（sqlite3.Row / dict）或原始字符串。
"""
import json


def format_user_department(level2, level3):
    l2 = (level2 or "").strip()
    l3 = (level3 or "").strip()
    if not l2:
        return ""
    return f"{l2}/{l3}" if l3 else l2


def split_department_field(department):
    dept = (department or "").strip()
    if "/" in dept:
        parts = dept.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return dept, ""


def user_dept_display(user_row):
    """用户二层/三层部门展示文本。"""
    keys = user_row.keys() if hasattr(user_row, "keys") else []
    dept_level2 = user_row["dept_level2"] if "dept_level2" in keys else ""
    dept_level3 = user_row["dept_level3"] if "dept_level3" in keys else ""
    department = user_row["department"] if "department" in keys else ""
    if not dept_level2 and department:
        dept_level2, dept_level3 = split_department_field(department)
    return format_user_department(dept_level2, dept_level3) or (department or "").strip()


def user_dept_pl_display(user_row):
    """部门与 PL 合并展示：二层/三层/PL；无三层则 二层/PL（空段自动省略）。

    候选人登记的「拓源人部门」「接口人部门」快照列统一使用该合并值。
    """
    keys = user_row.keys() if hasattr(user_row, "keys") else []
    pl = str((user_row["pl_group"] if "pl_group" in keys else "") or "").strip()
    dept = user_dept_display(user_row)
    return "/".join(p for p in (dept, pl) if p)


def parse_job_roles(raw):
    """解析 users.job_roles JSON 为岗位列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return []


def interviewer_matches_position(job_roles, position):
    """岗位筛选：未选岗位则全部；面试官未配置岗位则视为可匹配任意岗位。"""
    if not position:
        return True
    if not job_roles:
        return True
    return position in job_roles
