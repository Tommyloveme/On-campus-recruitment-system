# -*- coding: utf-8 -*-
"""数据库建表、迁移与演示数据。

分层约束：本模块只依赖 core / domain 层（配置与纯业务规则），
不得 import campus.services 或 campus.web（避免数据层反向依赖上层）。

- `SCHEMA` 是全部表结构的唯一数据源（CREATE TABLE IF NOT EXISTS，幂等）。
- `migrate()` 只做「老库补列 / 数据回填 / 历史清理」，新表一律进 SCHEMA。
- 普通用户基线模块权限来自 config/roles.json 内置角色 `user` 的 perms
  （campus.core.roles_store.role_perms），不在本文件重复维护。
"""
import json
import os
import sqlite3

from werkzeug.security import generate_password_hash

from campus.core.roles_store import role_bypass, role_perms
from campus.core.settings import DB_PATH, FEEDBACK_DIR, RESUME_DIR
from campus.db.connection import now_str
from campus.domain.employees import user_dept_display
from campus.domain.stage_routing import compute_current_stage

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    parent_id INTEGER REFERENCES groups(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    group_id INTEGER,
    supervisor TEXT DEFAULT '',
    department TEXT DEFAULT '',
    dept_level2 TEXT DEFAULT '',
    dept_level3 TEXT DEFAULT '',
    job_roles TEXT DEFAULT '[]',
    extra TEXT DEFAULT '{}',
    log_level INTEGER NOT NULL DEFAULT 10,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER,
    data TEXT NOT NULL,
    phone TEXT,
    resume_file TEXT,
    resume_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_phone_unique
    ON candidates(phone) WHERE phone IS NOT NULL AND phone != '';
CREATE TABLE IF NOT EXISTS candidates_raw_manual (
    phone TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates_raw_master (
    phone TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    action TEXT NOT NULL,
    candidate_id INTEGER,
    candidate_name TEXT,
    group_id INTEGER,
    module_key TEXT DEFAULT '',
    level INTEGER NOT NULL DEFAULT 10,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interviewer_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    interview_type TEXT NOT NULL,
    avail_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    group_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_iv_avail_unique
    ON interviewer_availability(user_id, interview_type, avail_date, start_time);
CREATE TABLE IF NOT EXISTS interview_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_type TEXT NOT NULL,
    interviewer_id INTEGER NOT NULL REFERENCES users(id),
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    avail_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    start_at TEXT NOT NULL,
    booked_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(interviewer_id, start_at, interview_type)
);
CREATE TABLE IF NOT EXISTS module_acl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    module_key TEXT NOT NULL,
    perm_visibility INTEGER NOT NULL DEFAULT 0,
    perm_read INTEGER NOT NULL DEFAULT 0,
    perm_write INTEGER NOT NULL DEFAULT 0,
    perm_manage INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(subject_type, subject_id, module_key)
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content_html TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    reply_html TEXT DEFAULT '',
    reply_by TEXT DEFAULT '',
    reply_at TEXT,
    created_at TEXT NOT NULL
);
"""


def _baseline_module_rows(uid, now):
    """普通用户基线权限行：来自 roles.json 内置角色 user 的 perms（唯一数据源）。"""
    rows = []
    for mk, flags in (role_perms("user") or {}).items():
        rows.append((
            "user", uid, mk,
            1 if flags.get("v") else 0, 1 if flags.get("r") else 0,
            1 if flags.get("w") else 0, 1 if flags.get("m") else 0, now,
        ))
    return rows


def _is_bypass_user(u):
    return u["role"] == "admin" or role_bypass(u["role"])


def migrate(db):
    """为老数据库补列 / 回填数据 / 清理历史结构（新表结构一律进 SCHEMA）。"""
    # 确保所有表/索引存在（SCHEMA 幂等，老库缺表时在此补齐）
    db.executescript(SCHEMA)

    # ---- 老库补列 -----------------------------------------------------------
    log_cols = {r["name"] for r in db.execute("PRAGMA table_info(logs)").fetchall()}
    if "module_key" not in log_cols:
        db.execute("ALTER TABLE logs ADD COLUMN module_key TEXT DEFAULT ''")
    if "level" not in log_cols:
        db.execute("ALTER TABLE logs ADD COLUMN level INTEGER NOT NULL DEFAULT 10")
        # 存量日志按动作类型回填默认等级（与 audit.DEFAULT_ACTION_LEVELS 保持一致）
        from campus.core.log_levels import DEFAULT_ACTION_LEVELS
        for action, lv in DEFAULT_ACTION_LEVELS.items():
            db.execute("UPDATE logs SET level=? WHERE action=?", (lv, action))
    db.execute("CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module_key, id)")

    # ---- 用户日志权限等级（1 最高、10 最低；管理员默认 1，普通用户默认 10） ----
    user_cols_pre = {r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()}
    if "log_level" not in user_cols_pre:
        db.execute("ALTER TABLE users ADD COLUMN log_level INTEGER NOT NULL DEFAULT 10")
        for u in db.execute("SELECT id, role FROM users").fetchall():
            if _is_bypass_user(u):
                db.execute("UPDATE users SET log_level=1 WHERE id=?", (u["id"],))
    cols = {r["name"] for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if "resume_file" not in cols:
        db.execute("ALTER TABLE candidates ADD COLUMN resume_file TEXT")
        db.execute("ALTER TABLE candidates ADD COLUMN resume_name TEXT")
    user_cols = {r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()}
    if "supervisor" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN supervisor TEXT DEFAULT ''")
    if "department" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN department TEXT DEFAULT ''")
    if "job_roles" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN job_roles TEXT DEFAULT '[]'")
    if "extra" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN extra TEXT DEFAULT '{}'")
    if "dept_level2" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN dept_level2 TEXT DEFAULT ''")
        db.execute("ALTER TABLE users ADD COLUMN dept_level3 TEXT DEFAULT ''")
        for row in db.execute("SELECT id, department FROM users").fetchall():
            dept = (row["department"] or "").strip()
            if "/" in dept:
                l2, l3 = dept.split("/", 1)
                l2, l3 = l2.strip(), l3.strip()
            else:
                l2, l3 = dept, ""
            db.execute(
                "UPDATE users SET dept_level2=?, dept_level3=? WHERE id=?",
                (l2, l3, row["id"]),
            )

    # 老库 candidates.group_id 曾为 NOT NULL：重建为可空
    cand_cols = {r["name"]: r for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if cand_cols.get("group_id") and cand_cols["group_id"]["notnull"]:
        db.executescript("""
        CREATE TABLE candidates_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups(id),
            data TEXT NOT NULL,
            resume_file TEXT,
            resume_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO candidates_new SELECT id, group_id, data, resume_file, resume_name, created_at, updated_at FROM candidates;
        DROP TABLE candidates;
        ALTER TABLE candidates_new RENAME TO candidates;
        """)

    group_cols = {r["name"] for r in db.execute("PRAGMA table_info(groups)").fetchall()}
    if "description" not in group_cols:
        try:
            db.execute("ALTER TABLE groups ADD COLUMN description TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    if "parent_id" not in group_cols:
        try:
            db.execute("ALTER TABLE groups ADD COLUMN parent_id INTEGER")
        except sqlite3.OperationalError:
            pass

    # ---- 候选人电话唯一标识（补列 + 去重回填 + 唯一索引） --------------------
    cand_cols = {r["name"] for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if "phone" not in cand_cols:
        db.execute("ALTER TABLE candidates ADD COLUMN phone TEXT")
    seen_phones = {}
    for row in db.execute("SELECT id, data, phone FROM candidates ORDER BY id").fetchall():
        data = json.loads(row["data"])
        ph = (row["phone"] or data.get("phone") or "").strip()
        if not ph:
            continue
        if ph in seen_phones:
            db.execute("UPDATE candidates SET phone=NULL WHERE id=?", (row["id"],))
            continue
        seen_phones[ph] = row["id"]
        if (row["phone"] or "").strip() != ph:
            db.execute("UPDATE candidates SET phone=? WHERE id=?", (ph, row["id"]))
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_phone_unique
        ON candidates(phone) WHERE phone IS NOT NULL AND phone != ''
    """)

    # ---- feedback 老库补列 ---------------------------------------------------
    fb_cols = {r["name"] for r in db.execute("PRAGMA table_info(feedback)").fetchall()}
    if fb_cols and "title" not in fb_cols:
        db.execute("ALTER TABLE feedback ADD COLUMN title TEXT NOT NULL DEFAULT ''")
    if fb_cols and "priority" not in fb_cols:
        db.execute("ALTER TABLE feedback ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
    if fb_cols and "reply_html" not in fb_cols:
        db.execute("ALTER TABLE feedback ADD COLUMN reply_html TEXT DEFAULT ''")
    if fb_cols and "reply_by" not in fb_cols:
        db.execute("ALTER TABLE feedback ADD COLUMN reply_by TEXT DEFAULT ''")
    if fb_cols and "reply_at" not in fb_cols:
        db.execute("ALTER TABLE feedback ADD COLUMN reply_at TEXT")

    # ---- 历史结构清理：用户分组/资源分组/模板/资源ACL 已取消 -----------------
    db.executescript("""
        DROP TABLE IF EXISTS user_group_members;
        DROP TABLE IF EXISTS user_groups;
        DROP TABLE IF EXISTS user_group_templates;
        DROP TABLE IF EXISTS permission_templates;
        DROP TABLE IF EXISTS acl;
        DROP TABLE IF EXISTS module_acl_meta;
    """)

    # 候选人统一归为共享池（取消资源分组）
    db.execute("UPDATE candidates SET group_id=NULL")

    # 历史角色收敛：非 roles.json 中定义的角色一律归为 user
    from campus.core.roles_store import role_keys
    known = set(role_keys()) or {"admin", "user"}
    placeholders = ",".join("?" * len(known))
    db.execute(
        f"UPDATE users SET role='user' WHERE role IS NULL OR role NOT IN ({placeholders})",
        list(known),
    )

    # 清理历史 user_group 主体授权（已取消用户分组）
    db.execute("DELETE FROM module_acl WHERE subject_type != 'user'")

    # ---- 为尚无任何模块权限的普通用户补齐基线（幂等） -------------------------
    now = now_str()
    for u in db.execute("SELECT id, role FROM users").fetchall():
        if _is_bypass_user(u):
            continue
        cnt = db.execute(
            "SELECT COUNT(*) AS c FROM module_acl WHERE subject_type='user' AND subject_id=?", (u["id"],)
        ).fetchone()["c"]
        if cnt == 0:
            db.executemany(
                "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                _baseline_module_rows(u["id"], now),
            )

    _backfill_candidate_employee_names(db)
    _backfill_raw_manual(db)
    _ensure_feedback_module_acl(db)
    _ensure_new_stage_module_acl(db)
    db.commit()


def _backfill_raw_manual(db):
    """历史迁移：手动原始表为空时，用预处理表（candidates）现状回填一份基线快照。

    历史数据无法区分手动与主数据来源，统一视为手动基线；后续主数据表刷新
    会把主数据行写入 candidates_raw_master，两表自此各自演进。
    """
    cnt = db.execute("SELECT COUNT(*) AS c FROM candidates_raw_manual").fetchone()["c"]
    if cnt > 0:
        return
    now = now_str()
    for row in db.execute("SELECT data, phone FROM candidates").fetchall():
        data = json.loads(row["data"])
        phone = (row["phone"] or data.get("phone") or "").strip()
        if not phone:
            continue
        snapshot = {k: v for k, v in data.items() if not k.startswith("_")}
        db.execute(
            "INSERT INTO candidates_raw_manual (phone, data, created_at, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(phone) DO NOTHING",
            (phone, json.dumps(snapshot, ensure_ascii=False), now, now),
        )


def _ensure_new_stage_module_acl(db):
    """历史迁移：为已有用户补齐后来新增的流程模块权限（继承所属板块的授权）。"""
    new_modules = (
        ("personality_test", 1, 1, 1, 0),
        ("qualification_interview", 1, 1, 1, 0),
        ("contract_signing", 1, 1, 1, 0),
    )
    now = now_str()
    for u in db.execute("SELECT id, role FROM users").fetchall():
        if _is_bypass_user(u):
            continue
        for k, v, r, w, m in new_modules:
            exists = db.execute(
                "SELECT id FROM module_acl WHERE subject_type='user' AND subject_id=? AND module_key=?",
                (u["id"], k),
            ).fetchone()
            if exists:
                continue
            inherit = db.execute(
                "SELECT perm_visibility, perm_read, perm_write, perm_manage FROM module_acl "
                "WHERE subject_type='user' AND subject_id=? AND module_key IN ('recruit_flow','offer_strategy')",
                (u["id"],),
            ).fetchall()
            if inherit:
                iv, ir, iw, im = inherit[0]
                db.execute(
                    "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                    "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                    "VALUES ('user', ?, ?, ?, ?, ?, ?, ?)",
                    (u["id"], k, iv or v, ir or r, iw or w, im or m, now),
                )
            else:
                db.execute(
                    "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                    "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                    "VALUES ('user', ?, ?, ?, ?, ?, ?, ?)",
                    (u["id"], k, v, r, w, m, now),
                )


def _ensure_feedback_module_acl(db):
    """历史迁移：为已有用户补齐问题反馈模块读权限（全员可查看）。"""
    now = now_str()
    for u in db.execute("SELECT id, role FROM users").fetchall():
        if _is_bypass_user(u):
            continue
        exists = db.execute(
            "SELECT id FROM module_acl WHERE subject_type='user' AND subject_id=? AND module_key='feedback'",
            (u["id"],),
        ).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                "VALUES ('user', ?, 'feedback', 1, 1, 0, 0, ?)",
                (u["id"], now),
            )


def _backfill_candidate_employee_names(db):
    """历史候选人：补全拓源人/接口人中文姓名与部门（列表展示用）。"""
    for row in db.execute("SELECT id, data FROM candidates").fetchall():
        data = json.loads(row["data"])
        changed = False
        for emp_key, name_key, dept_key in (
            ("sourcer", "sourcer_name", "sourcer_dept"),
            ("interface_person", "interface_person_name", "interface_dept"),
        ):
            emp = (data.get(emp_key) or "").strip()
            if not emp:
                continue
            if (data.get(name_key) or "").strip() and (data.get(dept_key) or "").strip():
                continue
            u = db.execute(
                "SELECT username, display_name, department, dept_level2, dept_level3 "
                "FROM users WHERE username=?",
                (emp,),
            ).fetchone()
            if not u:
                continue
            if not (data.get(name_key) or "").strip():
                data[name_key] = u["display_name"] or ""
                changed = True
            if not (data.get(dept_key) or "").strip():
                data[dept_key] = user_dept_display(u)
                changed = True
        if changed:
            db.execute(
                "UPDATE candidates SET data=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), row["id"]),
            )


def seed_demo(db):
    if db.execute("SELECT COUNT(*) AS c FROM users WHERE username != 'admin'").fetchone()["c"] > 0:
        print("已存在用户数据，跳过示例数据。")
        return
    demo_users = (
        ("lead01", "招聘主管老张", "李主管", "软件部/研发一组", "软件部", "研发一组"),
        ("hr01", "招聘专员小王", "李主管", "存储部", "存储部", ""),
        ("hr02", "招聘专员小李", "王主管", "软件部", "软件部", ""),
    )
    for username, display, sup, dept, l2, l3 in demo_users:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, extra, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (username, display, generate_password_hash("123456"), "user", None,
             sup, dept, l2, l3, "{}", now_str()),
        )
    samples = [
        {"name": "张伟", "phone": "13800000001", "interface_person": "刘洋",
              "dept_level3": "存储部", "registration_status": "已登记", "registration_source": "校园宣讲",
              "resume_screening_status": "通过", "qualification_status": "通过", "written_test_status": "已完成", "written_test_score": "85",
              "tech_interview_status": "已完成", "tech_interview_result": "通过",
              "manager_interview_status": "已完成", "manager_interview_result": "通过",
              "approval_status": "已通过", "salary_status": "已接受",
              "offer_status": "已接受", "sign_status": "已签约",
              "work_location": "深圳", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-07-15",
              "physical_exam_time": "2026-06-20", "physical_exam_done": "否", "onboard_booked": "是",
              "onboard_booked_time": "2026-07-15", "onboarded": "否", "onboard_risk": "低"},
        {"name": "李娜", "phone": "13800000002", "interface_person": "刘洋",
              "dept_level3": "计算部", "registration_status": "已登记",
              "qualification_status": "通过", "written_test_status": "已完成",
              "tech_interview_status": "已完成", "tech_interview_result": "通过",
              "manager_interview_status": "已完成", "manager_interview_result": "通过",
              "approval_status": "审批中", "salary_status": "谈薪中",
              "offer_status": "已发放", "sign_status": "未签约",
              "work_location": "杭州", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-08-01",
              "physical_exam_done": "否", "onboard_booked": "否", "onboarded": "否", "onboard_risk": "中"},
        {"name": "陈强", "phone": "13800000003", "interface_person": "孙敏",
              "dept_level3": "软件部", "registration_status": "已登记",
              "qualification_status": "通过", "written_test_status": "已预约",
              "tech_interview_status": "待预约",
              "work_location": "上海", "graduation_time": "2026-07-01",
              "onboarded": "否"},
    ]
    for data in samples:
        compute_current_stage(data)
        db.execute(
            "INSERT INTO candidates (group_id, data, phone, created_at, updated_at) VALUES (?,?,?,?,?)",
            (None, json.dumps(data, ensure_ascii=False), data.get("phone") or None, now_str(), now_str()),
        )
    # 示例用户按 roles.json 的 user 角色模板补齐基线模块权限
    now = now_str()
    for uname, *_rest in demo_users:
        u = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if u:
            db.executemany(
                "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                _baseline_module_rows(u["id"], now),
            )
    db.commit()
    print("已写入示例用户/候选人数据（lead01、hr01、hr02 / 123456）。")


def init_db(demo=False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(RESUME_DIR, exist_ok=True)
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    migrate(db)
    if db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, extra, log_level, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin", None,
             "", "", "{}", 1, now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        seed_demo(db)
    db.close()
