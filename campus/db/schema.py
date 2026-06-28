# -*- coding: utf-8 -*-
"""数据库建表、迁移与演示数据。"""
import json
import os
import sqlite3

from werkzeug.security import generate_password_hash

from campus.db.connection import now_str
from campus.settings import DB_PATH, RESUME_DIR
from campus.stage_engine import compute_current_stage

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
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    action TEXT NOT NULL,
    candidate_id INTEGER,
    candidate_name TEXT,
    group_id INTEGER,
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
"""


def migrate(db):
    """为老数据库补充新列/新表。"""
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
    db.executescript("""
    CREATE TABLE IF NOT EXISTS interviewer_availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        interview_type TEXT NOT NULL,
        avail_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        group_id INTEGER REFERENCES groups(id),
        created_at TEXT NOT NULL
    );
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
    """)
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

    # 权限管理：扩展 groups 表（保留以兼容旧 candidates.group_id 列，已不再使用）
    group_cols = {r["name"] for r in db.execute("PRAGMA table_info(groups)").fetchall()} if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='groups'").fetchone() else set()
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
    db.executescript("""
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
    """)

    # 候选人电话唯一标识
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

    # ---- 取消用户分组/资源分组/模板/资源ACL：删除相关表 ----
    db.executescript("""
        DROP TABLE IF EXISTS user_group_members;
        DROP TABLE IF EXISTS user_groups;
        DROP TABLE IF EXISTS user_group_templates;
        DROP TABLE IF EXISTS permission_templates;
        DROP TABLE IF EXISTS acl;
        DROP TABLE IF EXISTS module_acl_meta;
    """)

    # users.extra 列（存放自定义附属信息字段）
    user_cols = {r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()}
    if "extra" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN extra TEXT DEFAULT '{}'")

    # 候选人统一归为共享池（取消资源分组）
    db.execute("UPDATE candidates SET group_id=NULL")

    # role 收敛为 admin/user
    db.execute("UPDATE users SET role='user' WHERE role IS NULL OR role != 'admin'")

    # 清理历史 user_group 主体授权（已取消用户分组）
    db.execute("DELETE FROM module_acl WHERE subject_type != 'user'")

    # 为每位非 admin 用户补齐基线模块权限（仅当该用户尚无任何 module_acl 时，幂等）
    baseline = [
        ("registration", 1, 1, 1, 0),
        ("recruit_flow", 1, 1, 1, 0),
        ("resume_screening", 1, 1, 1, 0),
        ("qualification", 1, 1, 1, 0),
        ("written_test", 1, 1, 1, 0),
        ("tech_interview", 1, 1, 1, 0),
        ("manager_interview", 1, 1, 1, 0),
        ("offer_strategy", 1, 1, 1, 0),
        ("approval", 1, 1, 1, 0),
        ("salary", 1, 1, 1, 0),
        ("offer", 1, 1, 1, 0),
        ("onboarding", 1, 1, 1, 0),
    ]
    now = now_str()
    from campus.services.roles import role_bypass
    for u in db.execute("SELECT id, role FROM users").fetchall():
        if u["role"] == "admin" or role_bypass(u["role"]):
            continue
        cnt = db.execute(
            "SELECT COUNT(*) AS c FROM module_acl WHERE subject_type='user' AND subject_id=?", (u["id"],)
        ).fetchone()["c"]
        if cnt == 0:
            db.executemany(
                "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [("user", u["id"], k, v, r, w, m, now) for (k, v, r, w, m) in baseline],
            )
    db.commit()


def seed_demo(db):
    if db.execute("SELECT COUNT(*) AS c FROM users WHERE username != 'admin'").fetchone()["c"] > 0:
        print("已存在用户数据，跳过示例数据。")
        return
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, extra, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("lead01", "招聘主管老张", generate_password_hash("123456"), "user", None,
         "李主管", "软件部/研发一组", "软件部", "研发一组", "{}", now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, extra, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("hr01", "招聘专员小王", generate_password_hash("123456"), "user", None,
         "李主管", "存储部", "存储部", "", "{}", now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, extra, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("hr02", "招聘专员小李", generate_password_hash("123456"), "user", None,
         "王主管", "软件部", "软件部", "", "{}", now_str()),
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
    # 示例用户补齐基线模块权限
    baseline = [
        ("registration", 1, 1, 1, 0), ("recruit_flow", 1, 1, 1, 0),
        ("resume_screening", 1, 1, 1, 0), ("qualification", 1, 1, 1, 0),
        ("written_test", 1, 1, 1, 0), ("tech_interview", 1, 1, 1, 0),
        ("manager_interview", 1, 1, 1, 0), ("offer_strategy", 1, 1, 1, 0),
        ("approval", 1, 1, 1, 0), ("salary", 1, 1, 1, 0), ("offer", 1, 1, 1, 0),
        ("onboarding", 1, 1, 1, 0),
    ]
    now = now_str()
    for uname in ("lead01", "hr01", "hr02"):
        u = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if u:
            db.executemany(
                "INSERT INTO module_acl (subject_type, subject_id, module_key, "
                "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [("user", u["id"], k, v, r, w, m, now) for (k, v, r, w, m) in baseline],
            )
    db.commit()
    print("已写入示例用户/候选人数据（lead01、hr01、hr02 / 123456）。")


def init_db(demo=False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(RESUME_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    migrate(db)
    if db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, extra, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin", None,
             "", "", "{}", now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        seed_demo(db)
    db.close()
