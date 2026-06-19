# -*- coding: utf-8 -*-
"""用户资料与注册相关业务逻辑。"""
import json

from campus.db.connection import get_db
from campus.settings import load_app_config

DEFAULT_REGISTERABLE_JOB_ROLES = ("拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA")
DEFAULT_REGISTER_JOB_ROLES = ("拓源人", "接口人")


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
    group_name = None
    if u["group_id"]:
        row = get_db().execute("SELECT name FROM groups WHERE id=?", (u["group_id"],)).fetchone()
        group_name = row["name"] if row else None
    keys = u.keys() if hasattr(u, "keys") else []
    supervisor = u["supervisor"] if "supervisor" in keys else ""
    department = u["department"] if "department" in keys else ""
    job_roles = parse_job_roles(u["job_roles"] if "job_roles" in keys else None)
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "role": u["role"],
        "group_id": u["group_id"],
        "group_name": group_name,
        "supervisor": supervisor or "",
        "department": department or "",
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
    """登记阶段新增：仅自动带入拓源人部门（手填项不覆盖）。"""
    dept = (user["department"] if "department" in user.keys() else "") or ""
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
