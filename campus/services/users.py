# -*- coding: utf-8 -*-
"""用户资料与字段校验相关业务逻辑。

唯一性由工号(username)决定，其余均为附属信息。附属信息字段由
config/user_fields.json 配置：内置字段(builtin=true)对应 users 表列，
自定义字段存入 users.extra(JSON)。本系统不提供用户自助注册。
"""
import json
import re

from campus.core.settings import load_app_config, load_user_fields
from campus.db.connection import get_db, now_str
from campus.domain.employees import (
    format_user_department,
    parse_job_roles,
    user_dept_display,
)

CHINESE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]+$")


def security_config():
    return load_app_config().get("security", {})


def reserved_accounts():
    sec = security_config()
    accounts = set(sec.get("reserved_accounts", []))
    accounts.add("admin")
    return accounts


def user_fields_config():
    """返回用户附属信息字段配置（实时读取，便于热更新）。"""
    return load_user_fields()


def account_options_payload():
    """下发用户附属信息字段配置（供个人资料、用户管理弹窗渲染）。"""
    from campus.services.interviews import interview_cfg
    return {
        "user_fields": user_fields_config(),
        "interview_position_options": interview_cfg().get("position_options", []),
    }


def parse_job_roles_list(raw):
    return parse_job_roles(raw)


def normalize_job_roles_payload(body):
    """从请求体解析 job_roles 列表。"""
    if "job_roles" not in body:
        return None
    val = body.get("job_roles")
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return parse_job_roles(val)
    return []


def persist_user_columns(db, uid, fields, role, password=None, is_create=False, username=None, job_roles=None):
    """根据解析后的 fields（builtin/custom）写入用户表列与 extra JSON。"""
    b = fields["builtin"]
    c = fields["custom"]
    extra = json.dumps(c, ensure_ascii=False)
    jr = json.dumps(job_roles if job_roles is not None else [], ensure_ascii=False)
    if is_create:
        from werkzeug.security import generate_password_hash

        from campus.core.roles_store import role_bypass
        log_level = 1 if (role == "admin" or role_bypass(role)) else 10
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, "
            "supervisor, department, dept_level2, dept_level3, job_roles, extra, log_level, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, b.get("display_name", ""), generate_password_hash(password),
             role, None, b.get("supervisor", ""), b.get("department", ""),
             b.get("dept_level2", ""), b.get("dept_level3", ""), jr, extra, log_level, now_str()),
        )
    else:
        sql = (
            "UPDATE users SET display_name=?, role=?, supervisor=?, department=?, "
            "dept_level2=?, dept_level3=?, extra=?"
        )
        params = [b.get("display_name", ""), role, b.get("supervisor", ""), b.get("department", ""),
                  b.get("dept_level2", ""), b.get("dept_level3", ""), extra]
        if job_roles is not None:
            sql += ", job_roles=?"
            params.append(jr)
        sql += " WHERE id=?"
        params.append(uid)
        db.execute(sql, params)
        if password:
            from werkzeug.security import generate_password_hash
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(password), uid))


def builtin_fields():
    return [f for f in user_fields_config() if f.get("builtin")]


def custom_fields():
    return [f for f in user_fields_config() if not f.get("builtin")]


def field_def(key):
    for f in user_fields_config():
        if f["key"] == key:
            return f
    return None


def is_chinese_only(text):
    return bool(text) and CHINESE_NAME_RE.fullmatch(text)


def parse_extra(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def parse_user_profile_body(body, require_employee_id=False):
    """按 user_fields.json 校验并规范化附属信息字段，返回 (error, fields)。

    fields 包含：builtin 字段（写入内置列）与 custom 字段（写入 extra JSON）。
    employee_id 即工号(username)。
    """
    cfg = user_fields_config()
    employee_id = None
    if require_employee_id:
        employee_id = (body.get("employee_id") or body.get("username") or "").strip()
        digits = int(load_app_config().get("user_profile", {}).get("employee_id_digits", 8))
        if not employee_id:
            return "工号不能为空", None
        if not re.fullmatch(rf"\d{{{digits}}}", employee_id):
            return f"工号须为{digits}位数字", None

    builtin = {}
    custom = {}
    for f in cfg:
        key = f["key"]
        val = body.get(key)
        if val is not None:
            val = str(val).strip() if not isinstance(val, (list, dict)) else val
        required = bool(f.get("required"))
        if required and not val:
            return f"{f['label']}不能为空", None
        if f.get("pattern") == "chinese" and val and not is_chinese_only(val):
            return f"{f['label']}须为中文", None
        if f.get("type") == "select" and val and val not in (f.get("options") or []):
            return f"{f['label']}不在可选范围内", None
        if f.get("builtin"):
            builtin[key] = val or ""
        else:
            custom[key] = val or ""

    # department 自动由 dept_level2/level3 拼接（若配置了该内置字段）
    if "dept_level2" in builtin:
        builtin.setdefault("department", format_user_department(builtin.get("dept_level2"), builtin.get("dept_level3")))

    if employee_id is not None:
        builtin["employee_id"] = employee_id
    return None, {"builtin": builtin, "custom": custom}


def user_dict(u):
    """序列化用户：工号 + 角色 + 所有配置字段（builtin 列 + extra JSON）。"""
    from campus.core.roles_store import role_label
    keys = u.keys() if hasattr(u, "keys") else []
    extra = parse_extra(u["extra"] if "extra" in keys else None)
    out = {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "role": u["role"],
        "role_label": role_label(u["role"]),
        "job_roles": parse_job_roles(u["job_roles"] if "job_roles" in keys else None),
    }
    for f in user_fields_config():
        key = f["key"]
        if f.get("builtin"):
            out[key] = u[key] if key in keys else ""
        else:
            out[key] = extra.get(key, "")
    return out


def apply_role_to_user(db, uid, role_key):
    """将角色权限模板写入用户的 module_acl（覆盖该用户原有模块权限）。

    bypass 角色（如系统管理员）清空其 module_acl（依赖 admin_bypass 直通）。
    返回写入的条目数。
    """
    from campus.core.roles_store import get_role, role_bypass
    db.execute("DELETE FROM module_acl WHERE subject_type='user' AND subject_id=?", (uid,))
    if role_bypass(role_key):
        return 0
    r = get_role(role_key)
    perms = (r or {}).get("perms", {}) or {}
    now = now_str()
    cnt = 0
    for mk, flags in perms.items():
        if not flags or not (flags.get("v") or flags.get("r") or flags.get("w") or flags.get("m")):
            continue
        feats = flags.get("features") or {}
        feat_json = json.dumps(feats, ensure_ascii=False) if feats else ""
        db.execute(
            "INSERT INTO module_acl (subject_type, subject_id, module_key, "
            "perm_visibility, perm_read, perm_write, perm_manage, perm_features, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("user", uid, mk,
             1 if flags.get("v") else 0, 1 if flags.get("r") else 0,
             1 if flags.get("w") else 0, 1 if flags.get("m") else 0,
             feat_json, now),
        )
        cnt += 1
    return cnt


def lookup_employee_by_username(db, username):
    emp = (username or "").strip()
    if not emp:
        return None
    return db.execute("SELECT * FROM users WHERE username=?", (emp,)).fetchone()


def lookup_employee_for_registration(db, query):
    """登记页：工号精确匹配；姓名精确/唯一模糊匹配；数字工号后缀唯一匹配。"""
    q = (query or "").strip()
    if not q:
        return None
    row = lookup_employee_by_username(db, q)
    if row:
        return row
    rows = db.execute("SELECT * FROM users WHERE display_name=?", (q,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    rows = db.execute("SELECT * FROM users WHERE display_name LIKE ?", (f"%{q}%",)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if q.isdigit():
        rows = db.execute(
            "SELECT * FROM users WHERE username LIKE ? ORDER BY username",
            (f"%{q}",),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
    return None


def _employee_brief(row):
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "department": user_dept_display(row) or "",
    }


def _employee_search_where(q):
    """构建登记页用户联想 SQL 条件（工号/姓名/部门/主管）。"""
    like = f"%{q}%"
    prefix = f"{q}%"
    parts = [
        "username LIKE ?",
        "display_name LIKE ?",
        "department LIKE ?",
        "dept_level2 LIKE ?",
        "dept_level3 LIKE ?",
        "supervisor LIKE ?",
    ]
    params = [like] * 6
    if q.isdigit():
        parts.append("username LIKE ?")
        params.append(f"%{q}")
    return " OR ".join(parts), params, prefix


def search_employees_for_registration(db, query, limit=5):
    """登记页拓源人/接口人联想：SQL 过滤 + 相关性排序，返回前 limit 条。"""
    q = (query or "").strip()
    if not q:
        return {"items": [], "total": 0, "too_many": False}
    where, params, prefix = _employee_search_where(q)
    total = db.execute(f"SELECT COUNT(*) AS c FROM users WHERE {where}", params).fetchone()["c"]
    rows = db.execute(
        f"""SELECT * FROM users WHERE {where}
            ORDER BY
              CASE
                WHEN username = ? THEN 0
                WHEN display_name = ? THEN 1
                WHEN username LIKE ? THEN 2
                WHEN display_name LIKE ? THEN 3
                ELSE 4
              END,
              username
            LIMIT ?""",
        params + [q, q, prefix, prefix, limit],
    ).fetchall()
    items = [_employee_brief(r) for r in rows]
    return {"items": items, "total": total, "too_many": total > limit}


def apply_registration_employee_fields(db, data):
    """根据拓源人/接口人工号写入姓名、部门（保存时解析一次并落库，列表不再实时查用户表）。"""
    sourcer = (data.get("sourcer") or "").strip()
    if sourcer:
        row = lookup_employee_for_registration(db, sourcer)
        if row:
            data["sourcer"] = row["username"]
            data["sourcer_name"] = row["display_name"] or ""
            data["sourcer_dept"] = user_dept_display(row)
    else:
        data.pop("sourcer_name", None)
        data.pop("sourcer_dept", None)
    iface = (data.get("interface_person") or "").strip()
    if iface:
        row = lookup_employee_for_registration(db, iface)
        if row:
            data["interface_person"] = row["username"]
            data["interface_person_name"] = row["display_name"] or ""
            data["interface_dept"] = user_dept_display(row)
    else:
        data.pop("interface_person_name", None)
        data.pop("interface_dept", None)
    return data


def apply_registration_candidate_defaults(data, user):
    """登记阶段新增：隐藏主数据/手填项，部门由工号在保存时解析。"""
    data.pop("resume_id", None)
    data.pop("delivery_time", None)
    data.pop("work_location", None)
    data.pop("sourcer_dept", None)
    data.pop("interface_dept", None)
    return data


def validate_registration_manual_create(data):
    """登记阶段手动新增：除登记备注外必填；来源为「其他」须填自定义来源。"""
    labels = {
        "name": "候选人", "phone": "电话", "sourcer": "拓源人（填写工号）",
        "interface_person": "接口人（填写工号）",
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
    """拓源人、接口人均须为系统已创建的工号。"""
    errors = []
    emp = (sourcer or "").strip()
    if emp:
        if not lookup_employee_for_registration(db, emp):
            errors.append(f"拓源人工号「{emp}」尚未由系统管理员创建，请联系管理员添加账号")
    iface = (interface_person or "").strip()
    if iface:
        if not lookup_employee_for_registration(db, iface):
            errors.append(f"接口人工号「{iface}」尚未由系统管理员创建，请联系管理员添加账号")
    return "；".join(errors) if errors else None
