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
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
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
    phone TEXT,
    resume_id TEXT,
    current_stage TEXT DEFAULT 'registration',
    data TEXT NOT NULL,
    resume_file TEXT,
    resume_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_phone_unique
    ON candidates(phone) WHERE phone IS NOT NULL AND phone != '';
CREATE INDEX IF NOT EXISTS idx_candidates_resume ON candidates(resume_id);
CREATE INDEX IF NOT EXISTS idx_candidates_stage ON candidates(current_stage);
CREATE TABLE IF NOT EXISTS candidate_pipeline (
    candidate_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    current_stage TEXT NOT NULL DEFAULT 'registration',
    manual_stage TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_stage_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    entered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage_history_cand
    ON candidate_stage_history(candidate_id, id);
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
    perm_features TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(subject_type, subject_id, module_key)
);
CREATE TABLE IF NOT EXISTS data_hub (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    tab_key TEXT NOT NULL DEFAULT '',
    resume_id TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL,
    field_label TEXT DEFAULT '',
    value TEXT DEFAULT '',
    updated_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, tab_key, resume_id, field_key)
);
CREATE INDEX IF NOT EXISTS idx_data_hub_resume ON data_hub(resume_id);
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
    # 先补列再建索引（避免老库 executescript 时 idx 引用不存在列）
    cand_cols = {r["name"] for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if cand_cols and "resume_id" not in cand_cols:
        db.execute("ALTER TABLE candidates ADD COLUMN resume_id TEXT")
    if cand_cols and "current_stage" not in cand_cols:
        db.execute("ALTER TABLE candidates ADD COLUMN current_stage TEXT DEFAULT 'registration'")

    # 确保所有表/索引存在（SCHEMA 幂等，老库缺表时在此补齐）
    db.executescript(SCHEMA)

    # ---- 老库补列 -----------------------------------------------------------
    log_cols = {r["name"] for r in db.execute("PRAGMA table_info(logs)").fetchall()}
    if "module_key" not in log_cols:
        db.execute("ALTER TABLE logs ADD COLUMN module_key TEXT DEFAULT ''")
    if "level" not in log_cols:
        db.execute("ALTER TABLE logs ADD COLUMN level INTEGER NOT NULL DEFAULT 10")
    # 存量日志按动作类型回填默认等级（与 audit.DEFAULT_ACTION_LEVELS 保持一致）。
    # 早期代码可能已把敏感操作按默认 L10 写入，这里幂等修正。
    from campus.core.log_levels import DEFAULT_ACTION_LEVELS
    for action, lv in DEFAULT_ACTION_LEVELS.items():
        db.execute("UPDATE logs SET level=? WHERE action=? AND (level IS NULL OR level=10)", (lv, action))
    db.execute("CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module_key, id)")

    # ---- 模块细粒度特性权限列（JSON，{feature_key: 0|1}，缺省=允许） ----
    acl_cols = {r["name"] for r in db.execute("PRAGMA table_info(module_acl)").fetchall()}
    if "perm_features" not in acl_cols:
        db.execute("ALTER TABLE module_acl ADD COLUMN perm_features TEXT NOT NULL DEFAULT ''")

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
            group_id INTEGER,
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
    # 先去掉各表遗留的 group_id 列（携带对 groups 的外键），再删除 groups 表
    for table in ("users", "candidates", "interviewer_availability"):
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if "group_id" in cols:
            try:
                db.execute(f"ALTER TABLE {table} DROP COLUMN group_id")
            except sqlite3.OperationalError:
                pass
    db.executescript("""
        DROP TABLE IF EXISTS user_group_members;
        DROP TABLE IF EXISTS user_groups;
        DROP TABLE IF EXISTS user_group_templates;
        DROP TABLE IF EXISTS permission_templates;
        DROP TABLE IF EXISTS acl;
        DROP TABLE IF EXISTS module_acl_meta;
        DROP TABLE IF EXISTS groups;
    """)

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
    _migrate_chinese_field_keys(db)
    _migrate_pinyin_keys(db)
    _sync_candidate_index_columns(db)
    _seed_stage_history(db)
    _backfill_process_status(db)
    db.commit()


def _backfill_process_status(db):
    """为缺少「流程状态」的候选人按规则重算补齐（列表展示用）。"""
    from campus.db.field_store import field_get
    for row in db.execute("SELECT id, data FROM candidates").fetchall():
        data = json.loads(row["data"])
        if str(field_get(data, "process_status") or "").strip():
            continue
        stage = compute_current_stage(data)
        db.execute("UPDATE candidates SET data=?, current_stage=? WHERE id=?",
                   (json.dumps(data, ensure_ascii=False), stage, row["id"]))


def _pinyin_reverse_map(db):
    """拼音键 → 中文表头映射。

    反推来源：已上传的主数据 Excel 表头（最完整）、主数据原始表中文列名、
    data_hub 中文标签。用历史拼音算法对每个中文表头重放，得到 拼音→中文。
    """
    from campus.services.master_import import header_to_pinyin_key
    headers = set()

    # 1) 已上传的主数据 Excel 文件表头
    master_dir = os.path.join(os.path.dirname(DB_PATH), "master_import")
    if os.path.isdir(master_dir):
        try:
            from openpyxl import load_workbook
            for root, _dirs, files in os.walk(master_dir):
                for fn in files:
                    if not fn.lower().endswith(".xlsx"):
                        continue
                    try:
                        wb = load_workbook(os.path.join(root, fn),
                                           read_only=True, data_only=True)
                        for ws in wb.worksheets:
                            first = next(ws.iter_rows(max_row=1, values_only=True), ())
                            headers.update(str(h).strip() for h in first if h)
                    except Exception:
                        continue
        except ImportError:
            pass

    # 2) 主数据原始表「字段」命名空间的中文列名
    for row in db.execute("SELECT data FROM candidates_raw_master").fetchall():
        try:
            d = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        labels = d.get("字段")
        if isinstance(labels, dict):
            headers.update(k for k in labels if isinstance(k, str))

    # 3) data_hub 的中文标签
    for row in db.execute(
        "SELECT DISTINCT field_label FROM data_hub WHERE field_label != ''"
    ).fetchall():
        headers.add(row["field_label"])

    rev = {}
    for h in headers:
        h = (h or "").strip()
        if not h or all(ord(ch) < 128 for ch in h):
            continue
        py = header_to_pinyin_key(h)
        if py and py != h:
            rev.setdefault(py, h)
    return rev


def _migrate_pinyin_keys(db):
    """历史拼音键（如 nian_ling）→ 中文表头键（如 年龄）。"""
    rev = _pinyin_reverse_map(db)
    if not rev:
        return

    def _fix(d):
        changed = False
        for py, cn in rev.items():
            if py in d and cn not in d:
                d[cn] = d.pop(py)
                changed = True
            elif py in d:
                del d[py]
                changed = True
        return changed

    for table, pk in (
        ("candidates", "id"),
        ("candidates_raw_manual", "phone"),
    ):
        for row in db.execute(f"SELECT {pk}, data FROM {table}").fetchall():
            try:
                d = json.loads(row["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            if _fix(d):
                db.execute(f"UPDATE {table} SET data=? WHERE {pk}=?",
                           (json.dumps(d, ensure_ascii=False), row[pk]))

    for row in db.execute("SELECT phone, data FROM candidates_raw_master").fetchall():
        try:
            d = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        changed = False
        for ns in ("字段键", "fields"):
            sub = d.get(ns)
            if isinstance(sub, dict) and _fix(sub):
                changed = True
        if not isinstance(d.get("字段键"), dict) and not isinstance(d.get("fields"), dict):
            changed = _fix(d) or changed
        if changed:
            db.execute("UPDATE candidates_raw_master SET data=? WHERE phone=?",
                       (json.dumps(d, ensure_ascii=False), row["phone"]))

    for py, cn in rev.items():
        exists = db.execute(
            "SELECT 1 FROM data_hub WHERE field_key=? LIMIT 1", (py,)).fetchone()
        if not exists:
            continue
        db.execute(
            "UPDATE data_hub SET field_key=?, field_label=? WHERE field_key=? "
            "AND NOT EXISTS (SELECT 1 FROM data_hub d2 WHERE d2.source=data_hub.source "
            "AND d2.tab_key=data_hub.tab_key AND d2.resume_id=data_hub.resume_id AND d2.field_key=?)",
            (cn, cn, py, cn),
        )
        db.execute("DELETE FROM data_hub WHERE field_key=?", (py,))


def _seed_stage_history(db):
    """为无阶段历史的候选人补一条当前阶段的进入记录（停留时长统计基线）。"""
    for row in db.execute(
        "SELECT c.id, c.current_stage, c.updated_at, c.created_at FROM candidates c "
        "WHERE NOT EXISTS (SELECT 1 FROM candidate_stage_history h WHERE h.candidate_id=c.id)"
    ).fetchall():
        db.execute(
            "INSERT INTO candidate_stage_history (candidate_id, stage, entered_at) VALUES (?,?,?)",
            (row["id"], row["current_stage"] or "registration",
             row["updated_at"] or row["created_at"]),
        )


def _migrate_chinese_field_keys(db):
    """历史数据：已知英文字段键 → 中文 storage_key；未注册英文键保留。"""
    from campus.db.field_store import (
        build_field_registry,
        legacy_to_storage,
        normalize_record,
        reload_field_registry,
    )
    # 启动时按最新配置（阶段字段 + 主数据映射）重建注册表，保证新增映射字段立即生效
    build_field_registry(save=True)
    reload_field_registry()

    def _migrate_json(raw):
        if not raw:
            return raw
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw
        return json.dumps(normalize_record(data), ensure_ascii=False)

    for table, pk in (
        ("candidates", "id"),
        ("candidates_raw_manual", "phone"),
    ):
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if "data" not in cols:
            continue
        for row in db.execute(f"SELECT {pk}, data FROM {table}").fetchall():
            new_data = _migrate_json(row["data"])
            if new_data != row["data"]:
                db.execute(f"UPDATE {table} SET data=? WHERE {pk}=?", (new_data, row[pk]))

    # 主数据原始表：双命名空间分别规范化（fields → 字段键，内层键转中文）
    for row in db.execute("SELECT phone, data FROM candidates_raw_master").fetchall():
        try:
            d = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        flat = None
        for ns in ("字段键", "fields"):
            if isinstance(d.get(ns), dict):
                flat = d.pop(ns)
                break
        if flat is None:
            flat = {k: v for k, v in d.items() if k != "字段"}
            d = {"字段": d.get("字段") or {}}
        new = {"字段键": normalize_record(flat), "字段": d.get("字段") or {}}
        new_raw = json.dumps(new, ensure_ascii=False)
        if new_raw != row["data"]:
            db.execute("UPDATE candidates_raw_master SET data=? WHERE phone=?",
                       (new_raw, row["phone"]))

    for row in db.execute("SELECT id, field_key FROM data_hub").fetchall():
        cn = legacy_to_storage(row["field_key"])
        if cn and cn != row["field_key"]:
            db.execute("UPDATE data_hub SET field_key=? WHERE id=?", (cn, row["id"]))


def _sync_candidate_index_columns(db):
    """回填 candidates 索引列与 candidate_pipeline 表。"""
    from campus.db.field_store import field_get
    from campus.domain.stage_routing import MANUAL_STAGE_KEY

    cand_cols = {r["name"] for r in db.execute("PRAGMA table_info(candidates)").fetchall()}
    if "resume_id" not in cand_cols:
        db.execute("ALTER TABLE candidates ADD COLUMN resume_id TEXT")
    if "current_stage" not in cand_cols:
        db.execute("ALTER TABLE candidates ADD COLUMN current_stage TEXT DEFAULT 'registration'")

    now = now_str()
    for row in db.execute("SELECT id, data, phone, resume_id, current_stage FROM candidates").fetchall():
        data = json.loads(row["data"])
        rid = (row["resume_id"] or field_get(data, "resume_id") or "").strip()
        stage = (row["current_stage"] or field_get(data, "current_stage") or "registration").strip()
        manual = field_get(data, MANUAL_STAGE_KEY) or field_get(data, "manual_stage") or ""
        if rid != (row["resume_id"] or "") or stage != (row["current_stage"] or ""):
            db.execute(
                "UPDATE candidates SET resume_id=?, current_stage=? WHERE id=?",
                (rid or None, stage or "registration", row["id"]),
            )
        db.execute(
            "INSERT INTO candidate_pipeline (candidate_id, current_stage, manual_stage, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET "
            "current_stage=excluded.current_stage, manual_stage=excluded.manual_stage, "
            "updated_at=excluded.updated_at",
            (row["id"], stage or "registration", manual or "", now),
        )


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
            "INSERT INTO users (username, display_name, password_hash, role, supervisor, department, dept_level2, dept_level3, extra, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (username, display, generate_password_hash("123456"), "user",
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
            "INSERT INTO candidates (data, phone, created_at, updated_at) VALUES (?,?,?,?)",
            (json.dumps(data, ensure_ascii=False), data.get("phone") or None, now_str(), now_str()),
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
            "INSERT INTO users (username, display_name, password_hash, role, supervisor, department, extra, log_level, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin",
             "", "", "{}", 1, now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        seed_demo(db)
    db.close()
