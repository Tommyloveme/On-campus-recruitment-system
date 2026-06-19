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
    group_id INTEGER NOT NULL REFERENCES groups(id),
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
"""


def migrate(db):
    """为老数据库补充新列/新表。"""
    cols = {r["name"] for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if "resume_file" not in cols:
        db.execute("ALTER TABLE candidates ADD COLUMN resume_file TEXT")
        db.execute("ALTER TABLE candidates ADD COLUMN resume_name TEXT")
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
    db.commit()


def seed_demo(db):
    if db.execute("SELECT COUNT(*) AS c FROM groups").fetchone()["c"] > 0:
        print("已存在分组数据，跳过示例数据。")
        return
    g1 = db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", ("研发一组", now_str())).lastrowid
    g2 = db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", ("研发二组", now_str())).lastrowid
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
        ("lead01", "组管理员-老张", generate_password_hash("123456"), "group_admin", g1, now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
        ("hr01", "招聘专员-小王", generate_password_hash("123456"), "editor", g1, now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
        ("hr02", "招聘专员-小李", generate_password_hash("123456"), "editor", g2, now_str()),
    )
    samples = [
        (g1, {"name": "张伟", "phone": "13800000001", "interface_person": "刘洋",
              "dept_level3": "存储部", "registration_status": "已登记", "registration_source": "校园宣讲",
              "resume_screening_status": "通过", "qualification_status": "通过", "written_test_status": "已完成", "written_test_score": "85",
              "tech_interview_status": "已完成", "tech_interview_result": "通过",
              "manager_interview_status": "已完成", "manager_interview_result": "通过",
              "approval_status": "已通过", "salary_status": "已接受",
              "offer_status": "已接受", "sign_status": "已签约",
              "work_location": "深圳", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-07-15",
              "physical_exam_time": "2026-06-20", "physical_exam_done": "否", "onboard_booked": "是",
              "onboard_booked_time": "2026-07-15", "onboarded": "否", "onboard_risk": "低"}),
        (g1, {"name": "李娜", "phone": "13800000002", "interface_person": "刘洋",
              "dept_level3": "计算部", "registration_status": "已登记",
              "qualification_status": "通过", "written_test_status": "已完成",
              "tech_interview_status": "已完成", "tech_interview_result": "通过",
              "manager_interview_status": "已完成", "manager_interview_result": "通过",
              "approval_status": "审批中", "salary_status": "谈薪中",
              "offer_status": "已发放", "sign_status": "未签约",
              "work_location": "杭州", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-08-01",
              "physical_exam_done": "否", "onboard_booked": "否", "onboarded": "否", "onboard_risk": "中"}),
        (g2, {"name": "陈强", "phone": "13800000003", "interface_person": "孙敏",
              "dept_level3": "软件部", "registration_status": "已登记",
              "qualification_status": "通过", "written_test_status": "已预约",
              "tech_interview_status": "待预约",
              "work_location": "上海", "graduation_time": "2026-07-01",
              "onboarded": "否"}),
    ]
    for gid, data in samples:
        compute_current_stage(data)
        db.execute(
            "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
            (gid, json.dumps(data, ensure_ascii=False), now_str(), now_str()),
        )
    db.commit()
    print("已写入示例分组/用户/候选人数据（lead01 组管理员、hr01、hr02 / 123456）。")


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
            "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin", None, now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        seed_demo(db)
    db.close()
