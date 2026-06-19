# -*- coding: utf-8 -*-
"""用户资料与注册相关业务逻辑。"""
import json
import re

from campus.db.connection import get_db
from campus.settings import load_app_config

DEFAULT_REGISTERABLE_JOB_ROLES = ("拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA")
DEFAULT_REGISTER_JOB_ROLES = ("拓源人", "接口人")
DEFAULT_DEPT_LEVEL2 = ("存储部", "计算部", "网络部", "软件部")
DEFAULT_DEPT_LEVEL3 = ("块存储", "对象存储", "通用计算", "研发一组")
CHINESE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]+$")


def security_config():
    return load_app_config().get("security", {})


def reserved_accounts():
    sec = security_config()
    accounts = set(sec.get("reserved_accounts", []))
    accounts.add("admin")
    return accounts


def registerable_job_roles():
    sec = security_config()
    roles = sec.get("registerable_job_roles", DEFAULT_REGISTERABLE_JOB_ROLES)
    return list(roles)


def default_register_job_roles():
    sec = security_config()
    roles = sec.get("default_register_job_roles", DEFAULT_REGISTER_JOB_ROLES)
    return list(roles)


def user_profile_config():
    cfg = load_app_config().get("user_profile", {})
    return {
        "employee_id_digits": int(cfg.get("employee_id_digits", 8)),
        "dept_level2_options": list(cfg.get("dept_level2_options", DEFAULT_DEPT_LEVEL2)),
        "dept_level3_options": list(cfg.get("dept_level3_options", DEFAULT_DEPT_LEVEL3)),
    }


def register_options_payload():
    return {
        "job_roles": registerable_job_roles(),
        "default_job_roles": default_register_job_roles(),
        **user_profile_config(),
    }


def is_chinese_only(text):
    return bool(text) and CHINESE_NAME_RE.fullmatch(text)


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


def parse_user_profile_body(body, require_employee_id=False):
    """校验并规范化注册/个人资料字段，返回 (error_message, fields_dict)。"""
    cfg = user_profile_config()
    digits = cfg["employee_id_digits"]
    employee_id = None

    if require_employee_id:
        employee_id = (body.get("employee_id") or body.get("username") or "").strip()
        if not employee_id:
            return "工号不能为空", None
        if not re.fullmatch(rf"\d{{{digits}}}", employee_id):
            return f"工号须为{digits}位数字", None

    display_name = (body.get("display_name") or "").strip()
    supervisor = (body.get("supervisor") or "").strip()
    dept_level2 = (body.get("dept_level2") or "").strip()
    dept_level3 = (body.get("dept_level3") or "").strip()

    if not dept_level2 and body.get("department"):
        dept_level2, dept_level3_from_legacy = split_department_field(body.get("department"))
        if not dept_level3:
            dept_level3 = dept_level3_from_legacy

    if not display_name:
        return "姓名不能为空", None
    if not is_chinese_only(display_name):
        return "姓名须为中文", None
    if not supervisor:
        return "主管不能为空", None
    if not is_chinese_only(supervisor):
        return "主管须为中文", None
    if not dept_level2:
        return "请选择二层部门", None

    l2_opts = set(cfg["dept_level2_options"])
    l3_opts = set(cfg["dept_level3_options"])
    if dept_level2 not in l2_opts:
        return "二层部门不在可选范围内", None
    if dept_level3 and dept_level3 not in l3_opts:
        return "三层部门不在可选范围内", None

    fields = {
        "display_name": display_name,
        "supervisor": supervisor,
        "dept_level2": dept_level2,
        "dept_level3": dept_level3,
        "department": format_user_department(dept_level2, dept_level3),
    }
    if employee_id is not None:
        fields["employee_id"] = employee_id
    return None, fields


def parse_job_roles(raw):
    if isinstance(raw, list):
        roles = [str(r).strip() for r in raw if str(r).strip()]
    elif raw:
        try:
            roles = json.loads(raw)
            roles = roles if isinstance(roles, list) else []
        except (TypeError, json.JSONDecodeError):
            roles = []
    else:
        roles = []
    return roles


def normalize_job_roles(raw_roles):
    allowed = set(registerable_job_roles())
    roles = parse_job_roles(raw_roles)
    seen = set()
    out = []
    for r in roles:
        if r in allowed and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def user_dict(u):
    keys = u.keys() if hasattr(u, "keys") else []
    supervisor = u["supervisor"] if "supervisor" in keys else ""
    department = u["department"] if "department" in keys else ""
    dept_level2 = u["dept_level2"] if "dept_level2" in keys else ""
    dept_level3 = u["dept_level3"] if "dept_level3" in keys else ""
    if not dept_level2 and department:
        dept_level2, dept_level3 = split_department_field(department)
    if not department:
        department = format_user_department(dept_level2, dept_level3)
    job_roles = parse_job_roles(u["job_roles"] if "job_roles" in keys else None)
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "role": u["role"],
        "supervisor": supervisor or "",
        "department": department or "",
        "dept_level2": dept_level2 or "",
        "dept_level3": dept_level3 or "",
        "job_roles": job_roles,
    }


def resolve_group_id_for_user(department, explicit_group_id=None):
    if explicit_group_id:
        return explicit_group_id
    db = get_db()
    dept = (department or "").strip()
    if dept:
        row = db.execute("SELECT id FROM groups WHERE name=?", (dept,)).fetchone()
        if row:
            return row["id"]
    row = db.execute("SELECT id FROM groups ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def apply_registration_candidate_defaults(data, user):
    """登记阶段新增：仅自动带入拓源人部门（二层部门，手填项不覆盖）。"""
    keys = user.keys() if hasattr(user, "keys") else []
    dept_level2 = user["dept_level2"] if "dept_level2" in keys else ""
    department = user["department"] if "department" in keys else ""
    if not dept_level2 and department:
        dept_level2, _ = split_department_field(department)
    dept = (dept_level2 or department or "").strip()
    if dept and not str(data.get("sourcer_dept") or "").strip():
        data["sourcer_dept"] = dept
    data.pop("resume_id", None)
    data.pop("work_location", None)
    data.pop("interface_dept", None)
    return data


def validate_registration_manual_create(data):
    """登记阶段手动新增：除登记备注外必填；来源为「其他」须填自定义来源。"""
    labels = {
        "name": "候选人", "phone": "电话", "sourcer": "拓源人（填写工号）",
        "interface_person": "接口人（填写姓名）",
        "education": "学历", "school": "毕业院校", "major": "专业",
        "registration_source": "来源渠道",
    }
    required_keys = list(labels.keys())
    missing = [labels[k] for k in required_keys if not str(data.get(k) or "").strip()]
    if data.get("registration_source") == "其他":
        if not str(data.get("registration_source_custom") or "").strip():
            missing.append("自定义简历来源")
    return missing


def validate_registration_user_refs(db, sourcer, interface_person):
    """拓源人须为已注册工号，接口人须为已注册姓名。"""
    errors = []
    emp = (sourcer or "").strip()
    if emp:
        if not db.execute("SELECT id FROM users WHERE username=?", (emp,)).fetchone():
            errors.append(f"拓源人工号「{emp}」未在本系统注册，请先完成账号注册")
    name = (interface_person or "").strip()
    if name:
        if not db.execute("SELECT id FROM users WHERE display_name=?", (name,)).fetchone():
            errors.append(f"接口人「{name}」未在本系统注册，请先完成账号注册")
    return "；".join(errors) if errors else None
