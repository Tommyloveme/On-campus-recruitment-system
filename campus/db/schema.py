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
    role TEXT NOT NULL DEFAULT 'editor',
    group_id INTEGER REFERENCES groups(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER REFERENCES groups(id),
    data TEXT NOT NULL,
    resume_file TEXT,
    resume_name TEXT,
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
CREATE TABLE IF NOT EXISTS user_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    parent_id INTEGER REFERENCES user_groups(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(group_id, user_id)
);
CREATE TABLE IF NOT EXISTS user_group_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    member_usernames TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permission_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    perm_visibility INTEGER NOT NULL DEFAULT 1,
    perm_read INTEGER NOT NULL DEFAULT 1,
    perm_write INTEGER NOT NULL DEFAULT 0,
    perm_manage INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    perm_visibility INTEGER NOT NULL DEFAULT 0,
    perm_read INTEGER NOT NULL DEFAULT 0,
    perm_write INTEGER NOT NULL DEFAULT 0,
    perm_manage INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(subject_type, subject_id, resource_type, resource_id)
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
CREATE TABLE IF NOT EXISTS module_acl_meta (
    module_key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0
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

    # 权限管理：扩展 groups 表 + 新增用户分组/成员/模板/权限模板/ACL 表
    group_cols = {r["name"] for r in db.execute("PRAGMA table_info(groups)").fetchall()}
    if "description" not in group_cols:
        db.execute("ALTER TABLE groups ADD COLUMN description TEXT DEFAULT ''")
    if "parent_id" not in group_cols:
        db.execute("ALTER TABLE groups ADD COLUMN parent_id INTEGER REFERENCES groups(id)")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS user_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            parent_id INTEGER REFERENCES user_groups(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            UNIQUE(group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS user_group_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            member_usernames TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permission_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            perm_visibility INTEGER NOT NULL DEFAULT 1,
            perm_read INTEGER NOT NULL DEFAULT 1,
            perm_write INTEGER NOT NULL DEFAULT 0,
            perm_manage INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS acl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_type TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id INTEGER NOT NULL,
            perm_visibility INTEGER NOT NULL DEFAULT 0,
            perm_read INTEGER NOT NULL DEFAULT 0,
            perm_write INTEGER NOT NULL DEFAULT 0,
            perm_manage INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(subject_type, subject_id, resource_type, resource_id)
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
        CREATE TABLE IF NOT EXISTS module_acl_meta (
            module_key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0
        );
    """)

    # 首次启用权限管理：写入内置权限模板
    if db.execute("SELECT COUNT(*) AS c FROM permission_templates").fetchone()["c"] == 0:
        now = now_str()
        db.executemany(
            "INSERT INTO permission_templates (name, description, perm_visibility, perm_read, perm_write, perm_manage, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                ("只读访客", "仅可查看，不可修改", 1, 1, 0, 0, now),
                ("协作编辑", "可查看与编辑，不可管理权限", 1, 1, 1, 0, now),
                ("项目管理员", "可查看、编辑并管理权限", 1, 1, 1, 1, now),
                ("完全不可见", "在列表与搜索中均不展示", 0, 0, 0, 0, now),
            ],
        )

    # ---- 取消业务角色：role 收敛为 admin/user；建默认分组；存量用户入组；基线模块授权 ----
    # 1) role 收敛（admin 保留，其余一律 user）
    db.execute("UPDATE users SET role='user' WHERE role IS NULL OR role != 'admin'")
    # 2) 确保默认分组存在
    dg = db.execute("SELECT id FROM user_groups WHERE name=?", ("默认分组",)).fetchone()
    if not dg:
        db.execute(
            "INSERT INTO user_groups (name, description, parent_id, created_at) VALUES (?,?,?,?)",
            ("默认分组", "新建用户默认归属，基线权限由管理员配置", None, now_str()),
        )
        dg = db.execute("SELECT id FROM user_groups WHERE name=?", ("默认分组",)).fetchone()
    dg_id = dg["id"]
    # 3) 所有非 admin 用户加入默认分组
    existing_members = {
        (r["group_id"], r["user_id"]) for r in db.execute(
            "SELECT group_id, user_id FROM user_group_members WHERE group_id=?", (dg_id,)
        ).fetchall()
    }
    for u in db.execute("SELECT id, role FROM users").fetchall():
        if u["role"] == "admin":
            continue
        if (dg_id, u["id"]) not in existing_members:
            db.execute(
                "INSERT INTO user_group_members (group_id, user_id, created_at) VALUES (?,?,?)",
                (dg_id, u["id"], now_str()),
            )
    # 4) 默认分组基线模块授权（仅当该分组尚无任何 module_acl 时写入，幂等）
    cnt = db.execute(
        "SELECT COUNT(*) AS c FROM module_acl WHERE subject_type='user_group' AND subject_id=?", (dg_id,)
    ).fetchone()["c"]
    if cnt == 0:
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
        db.executemany(
            "INSERT INTO module_acl (subject_type, subject_id, module_key, "
            "perm_visibility, perm_read, perm_write, perm_manage, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [("user_group", dg_id, k, v, r, w, m, now_str()) for (k, v, r, w, m) in baseline],
        )
    db.commit()


def seed_demo(db):
    if db.execute("SELECT COUNT(*) AS c FROM users WHERE username != 'admin'").fetchone()["c"] > 0:
        print("已存在用户数据，跳过示例数据。")
        return
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, job_roles, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("lead01", "招聘主管老张", generate_password_hash("123456"), "user", None,
         "李主管", "软件部/研发一组", "软件部", "研发一组",
         json.dumps([], ensure_ascii=False), now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, job_roles, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("hr01", "招聘专员小王", generate_password_hash("123456"), "user", None,
         "李主管", "存储部", "存储部", "",
         json.dumps([], ensure_ascii=False), now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, dept_level2, dept_level3, job_roles, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("hr02", "招聘专员小李", generate_password_hash("123456"), "user", None,
         "王主管", "软件部", "软件部", "",
         json.dumps([], ensure_ascii=False), now_str()),
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
            "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
            (None, json.dumps(data, ensure_ascii=False), now_str(), now_str()),
        )
    # 示例用户加入默认分组以获得基线模块权限
    dg = db.execute("SELECT id FROM user_groups WHERE name=?", ("默认分组",)).fetchone()
    if dg:
        for uname in ("lead01", "hr01", "hr02"):
            u = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
            if u:
                db.execute(
                    "INSERT OR IGNORE INTO user_group_members (group_id, user_id, created_at) VALUES (?,?,?)",
                    (dg["id"], u["id"], now_str()),
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
            "INSERT INTO users (username, display_name, password_hash, role, group_id, supervisor, department, job_roles, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin", None,
             "", "", "[]", now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        seed_demo(db)
    db.close()
