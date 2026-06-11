# -*- coding: utf-8 -*-
"""校招候选人管理系统 - 跨平台（Windows / SUSE Linux）

技术栈：Flask + SQLite（标准库 sqlite3），Excel 导入使用 openpyxl。
字段通过 config/fields.json 配置：导入哪些列、网页显示哪些列均可配置。
"""
import io
import json
import os
import sqlite3
import sys
import secrets
from datetime import datetime
from functools import wraps

from flask import Flask, g, jsonify, request, session, send_file, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from openpyxl import Workbook, load_workbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "candidates.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config", "fields.json")
SECRET_PATH = os.path.join(BASE_DIR, "data", ".secret_key")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


# ---------------------------------------------------------------- 基础设施
def _ensure_secret():
    os.makedirs(os.path.dirname(SECRET_PATH), exist_ok=True)
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_PATH, encoding="utf-8") as f:
        return f.read().strip()


app.secret_key = _ensure_secret()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def load_fields():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["fields"]


def save_fields(fields):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["fields"] = fields
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 数据库初始化
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
    role TEXT NOT NULL DEFAULT 'editor',   -- admin / editor / viewer
    group_id INTEGER REFERENCES groups(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    data TEXT NOT NULL,                    -- JSON: {field_key: value}
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    action TEXT NOT NULL,                  -- create / update / delete / import
    candidate_id INTEGER,
    candidate_name TEXT,
    group_id INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_db(demo=False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cur = db.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("admin", "系统管理员", generate_password_hash("admin123"), "admin", None, now_str()),
        )
        db.commit()
        print("已创建默认管理员账号: admin / admin123")
    if demo:
        _seed_demo(db)
    db.close()


def _seed_demo(db):
    if db.execute("SELECT COUNT(*) AS c FROM groups").fetchone()["c"] > 0:
        print("已存在分组数据，跳过示例数据。")
        return
    g1 = db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", ("研发一组", now_str())).lastrowid
    g2 = db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", ("研发二组", now_str())).lastrowid
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
        ("hr01", "招聘专员-小王", generate_password_hash("123456"), "editor", g1, now_str()),
    )
    db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
        ("hr02", "招聘专员-小李", generate_password_hash("123456"), "editor", g2, now_str()),
    )
    samples = [
        (g1, {"name": "张伟", "phone": "13800000001", "interface_manager": "王经理", "interface_person": "刘洋",
              "dept_level2": "云计算BG", "dept_level3": "存储部", "offer_status": "已接受", "sign_status": "已签约",
              "work_location": "深圳", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-07-15",
              "physical_exam_time": "2026-06-20", "physical_exam_done": "否", "onboard_booked": "是",
              "onboard_booked_time": "2026-07-15", "onboarded": "否", "onboard_risk": "低"}),
        (g1, {"name": "李娜", "phone": "13800000002", "interface_manager": "王经理", "interface_person": "刘洋",
              "dept_level2": "云计算BG", "dept_level3": "计算部", "offer_status": "已发放", "sign_status": "未签约",
              "work_location": "杭州", "graduation_time": "2026-06-30", "expected_onboard_time": "2026-08-01",
              "physical_exam_done": "否", "onboard_booked": "否", "onboarded": "否", "onboard_risk": "中"}),
        (g2, {"name": "陈强", "phone": "13800000003", "interface_manager": "赵经理", "interface_person": "孙敏",
              "dept_level2": "终端BG", "dept_level3": "软件部", "offer_status": "已接受", "sign_status": "已签约",
              "work_location": "上海", "graduation_time": "2026-07-01", "expected_onboard_time": "2026-07-20",
              "physical_exam_time": "2026-06-25", "physical_exam_done": "是", "onboard_booked": "是",
              "onboard_booked_time": "2026-07-20", "onboarded": "否", "onboard_risk": "无"}),
    ]
    for gid, data in samples:
        db.execute(
            "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
            (gid, json.dumps(data, ensure_ascii=False), now_str(), now_str()),
        )
    db.commit()
    print("已写入示例分组/用户/候选人数据（hr01、hr02 / 123456）。")


# ---------------------------------------------------------------- 权限
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        g.user = user
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        if user["role"] != "admin":
            return jsonify({"error": "需要管理员权限"}), 403
        g.user = user
        return fn(*a, **kw)
    return wrapper


def can_edit_group(user, group_id):
    if user["role"] == "admin":
        return True
    return user["role"] == "editor" and user["group_id"] == group_id


# ---------------------------------------------------------------- 日志
def add_log(user, action, message, candidate_id=None, candidate_name=None, group_id=None):
    get_db().execute(
        "INSERT INTO logs (user_name, action, candidate_id, candidate_name, group_id, message, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (user["display_name"], action, candidate_id, candidate_name, group_id, message, now_str()),
    )


# ---------------------------------------------------------------- 认证接口
@app.post("/api/login")
def api_login():
    body = request.get_json(force=True)
    user = get_db().execute("SELECT * FROM users WHERE username=?", (body.get("username", ""),)).fetchone()
    if not user or not check_password_hash(user["password_hash"], body.get("password", "")):
        return jsonify({"error": "用户名或密码错误"}), 401
    session["uid"] = user["id"]
    return jsonify(user_dict(user))


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
@login_required
def api_me():
    return jsonify(user_dict(g.user))


def user_dict(u):
    group_name = None
    if u["group_id"]:
        row = get_db().execute("SELECT name FROM groups WHERE id=?", (u["group_id"],)).fetchone()
        group_name = row["name"] if row else None
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"],
            "role": u["role"], "group_id": u["group_id"], "group_name": group_name}


# ---------------------------------------------------------------- 字段配置
@app.get("/api/config")
@login_required
def api_config():
    return jsonify({"fields": load_fields()})


@app.put("/api/config")
@admin_required
def api_config_update():
    """管理员可在线调整字段的显示/编辑/导入开关，写回 fields.json。"""
    body = request.get_json(force=True)
    updates = {f["key"]: f for f in body.get("fields", [])}
    fields = load_fields()
    for f in fields:
        if f["key"] in updates:
            u = updates[f["key"]]
            for attr in ("visible", "editable", "importable", "label", "excel_column"):
                if attr in u:
                    f[attr] = u[attr]
    save_fields(fields)
    add_log(g.user, "config", f"{g.user['display_name']} 调整了字段显示配置")
    get_db().commit()
    return jsonify({"fields": fields})


# ---------------------------------------------------------------- 分组
@app.get("/api/groups")
@login_required
def api_groups():
    rows = get_db().execute(
        "SELECT g.*, (SELECT COUNT(*) FROM candidates c WHERE c.group_id=g.id) AS candidate_count "
        "FROM groups g ORDER BY g.id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/groups")
@admin_required
def api_group_create():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"error": "分组名不能为空"}), 400
    db = get_db()
    try:
        db.execute("INSERT INTO groups (name, created_at) VALUES (?,?)", (name, now_str()))
    except sqlite3.IntegrityError:
        return jsonify({"error": "分组名已存在"}), 400
    add_log(g.user, "group", f"{g.user['display_name']} 创建了分组「{name}」")
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/groups/<int:gid>")
@admin_required
def api_group_delete(gid):
    db = get_db()
    row = db.execute("SELECT name FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return jsonify({"error": "分组不存在"}), 404
    if db.execute("SELECT COUNT(*) AS c FROM candidates WHERE group_id=?", (gid,)).fetchone()["c"] > 0:
        return jsonify({"error": "该分组下仍有候选人，无法删除"}), 400
    db.execute("UPDATE users SET group_id=NULL WHERE group_id=?", (gid,))
    db.execute("DELETE FROM groups WHERE id=?", (gid,))
    add_log(g.user, "group", f"{g.user['display_name']} 删除了分组「{row['name']}」")
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 用户管理
@app.get("/api/users")
@admin_required
def api_users():
    rows = get_db().execute(
        "SELECT u.id, u.username, u.display_name, u.role, u.group_id, g.name AS group_name "
        "FROM users u LEFT JOIN groups g ON g.id=u.group_id ORDER BY u.id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/users")
@admin_required
def api_user_create():
    b = request.get_json(force=True)
    username = (b.get("username") or "").strip()
    if not username or not b.get("password"):
        return jsonify({"error": "用户名和密码不能为空"}), 400
    role = b.get("role", "editor")
    if role not in ("admin", "editor", "viewer"):
        return jsonify({"error": "角色不合法"}), 400
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, group_id, created_at) VALUES (?,?,?,?,?,?)",
            (username, b.get("display_name") or username, generate_password_hash(b["password"]),
             role, b.get("group_id"), now_str()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "用户名已存在"}), 400
    add_log(g.user, "user", f"{g.user['display_name']} 创建了用户「{b.get('display_name') or username}」")
    db.commit()
    return jsonify({"ok": True})


@app.put("/api/users/<int:uid>")
@admin_required
def api_user_update(uid):
    b = request.get_json(force=True)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    role = b.get("role", user["role"])
    db.execute(
        "UPDATE users SET display_name=?, role=?, group_id=? WHERE id=?",
        (b.get("display_name", user["display_name"]), role, b.get("group_id", user["group_id"]), uid),
    )
    if b.get("password"):
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(b["password"]), uid))
    add_log(g.user, "user", f"{g.user['display_name']} 更新了用户「{user['display_name']}」的信息")
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/users/<int:uid>")
@admin_required
def api_user_delete(uid):
    if uid == g.user["id"]:
        return jsonify({"error": "不能删除自己"}), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    add_log(g.user, "user", f"{g.user['display_name']} 删除了用户「{user['display_name']}」")
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 候选人
def candidate_dict(row, group_names=None):
    data = json.loads(row["data"])
    gname = (group_names or {}).get(row["group_id"])
    if gname is None:
        r = get_db().execute("SELECT name FROM groups WHERE id=?", (row["group_id"],)).fetchone()
        gname = r["name"] if r else ""
    return {"id": row["id"], "group_id": row["group_id"], "group_name": gname,
            "updated_at": row["updated_at"], "data": data}


def group_name_map():
    return {r["id"]: r["name"] for r in get_db().execute("SELECT id, name FROM groups").fetchall()}


@app.get("/api/candidates")
@login_required
def api_candidates():
    db = get_db()
    sql = "SELECT * FROM candidates"
    params = []
    if g.user["role"] != "admin":
        if not g.user["group_id"]:
            return jsonify([])
        sql += " WHERE group_id=?"
        params.append(g.user["group_id"])
    elif request.args.get("group_id"):
        sql += " WHERE group_id=?"
        params.append(int(request.args["group_id"]))
    sql += " ORDER BY updated_at DESC"
    rows = db.execute(sql, params).fetchall()
    names = group_name_map()
    result = [candidate_dict(r, names) for r in rows]
    q = (request.args.get("q") or "").strip()
    if q:
        result = [c for c in result
                  if any(q in str(v) for v in c["data"].values()) or q in c["group_name"]]
    return jsonify(result)


@app.post("/api/candidates")
@login_required
def api_candidate_create():
    b = request.get_json(force=True)
    group_id = b.get("group_id") or g.user["group_id"]
    if not group_id:
        return jsonify({"error": "请指定分组"}), 400
    if not can_edit_group(g.user, group_id):
        return jsonify({"error": "无该分组的编辑权限"}), 403
    fields = load_fields()
    data = {f["key"]: str(b.get("data", {}).get(f["key"], "") or "").strip() for f in fields if f.get("editable")}
    if not data.get("name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
        (group_id, json.dumps(data, ensure_ascii=False), now_str(), now_str()),
    )
    gname = group_name_map().get(group_id, "")
    add_log(g.user, "create", f"{g.user['display_name']} 新增了候选人「{data['name']}」（{gname}）",
            cur.lastrowid, data["name"], group_id)
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.put("/api/candidates/<int:cid>")
@login_required
def api_candidate_update(cid):
    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_group(g.user, row["group_id"]):
        return jsonify({"error": "无该分组的编辑权限"}), 403
    old = json.loads(row["data"])
    incoming = request.get_json(force=True).get("data", {})
    fields = load_fields()
    labels = {f["key"]: f["label"] for f in fields}
    new = dict(old)
    changes = []
    for f in fields:
        if not f.get("editable") or f["key"] not in incoming:
            continue
        k = f["key"]
        nv = str(incoming[k] or "").strip()
        ov = str(old.get(k, "") or "")
        if nv != ov:
            new[k] = nv
            changes.append(f"{labels[k]}：{ov or '空'} → {nv or '空'}")
    if not changes:
        return jsonify({"ok": True, "changed": 0})
    if not new.get("name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400
    db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
               (json.dumps(new, ensure_ascii=False), now_str(), cid))
    name = new.get("name") or old.get("name", "")
    add_log(g.user, "update",
            f"{g.user['display_name']} 修改了「{name}」：" + "；".join(changes),
            cid, name, row["group_id"])
    db.commit()
    return jsonify({"ok": True, "changed": len(changes)})


@app.delete("/api/candidates/<int:cid>")
@login_required
def api_candidate_delete(cid):
    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_group(g.user, row["group_id"]):
        return jsonify({"error": "无该分组的编辑权限"}), 403
    name = json.loads(row["data"]).get("name", "")
    db.execute("DELETE FROM candidates WHERE id=?", (cid,))
    add_log(g.user, "delete", f"{g.user['display_name']} 删除了候选人「{name}」", cid, name, row["group_id"])
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- Excel 导入/模板
@app.get("/api/import/template")
@login_required
def api_template():
    fields = [f for f in load_fields() if f.get("importable")]
    wb = Workbook()
    ws = wb.active
    ws.title = "候选人导入模板"
    for i, f in enumerate(fields, start=1):
        ws.cell(row=1, column=i, value=f["excel_column"])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, len(f["excel_column"]) * 2 + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="候选人导入模板.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/import")
@login_required
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "请选择Excel文件"}), 400
    group_id = request.form.get("group_id", type=int) or g.user["group_id"]
    if not group_id:
        return jsonify({"error": "请指定导入的分组"}), 400
    if not can_edit_group(g.user, group_id):
        return jsonify({"error": "无该分组的编辑权限"}), 403

    try:
        wb = load_workbook(request.files["file"], data_only=True)
    except Exception:
        return jsonify({"error": "文件解析失败，请上传 .xlsx 格式文件"}), 400
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return jsonify({"error": "Excel内容为空"}), 400

    fields = [f for f in load_fields() if f.get("importable")]
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    col_map = {}  # 列下标 -> field key
    for idx, h in enumerate(header):
        for f in fields:
            if h == f["excel_column"] or h == f["label"]:
                col_map[idx] = f["key"]
                break
    if "name" not in col_map.values():
        return jsonify({"error": "Excel中未找到“候选人”列，请参考导入模板"}), 400

    def cell_str(v):
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        return str(v).strip()

    db = get_db()
    existing = db.execute("SELECT * FROM candidates WHERE group_id=?", (group_id,)).fetchall()
    by_phone = {}
    by_name = {}
    for r in existing:
        d = json.loads(r["data"])
        if d.get("phone"):
            by_phone[d["phone"]] = r
        if d.get("name"):
            by_name[d["name"]] = r

    created = updated = skipped = 0
    for raw in rows[1:]:
        data = {}
        for idx, key in col_map.items():
            if idx < len(raw):
                data[key] = cell_str(raw[idx])
        if not data.get("name"):
            skipped += 1
            continue
        match = by_phone.get(data.get("phone", "")) or by_name.get(data["name"])
        if match:
            old = json.loads(match["data"])
            merged = dict(old)
            changed = False
            for k, v in data.items():
                if v and str(old.get(k, "")) != v:
                    merged[k] = v
                    changed = True
            if changed:
                db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                           (json.dumps(merged, ensure_ascii=False), now_str(), match["id"]))
                updated += 1
        else:
            cur = db.execute("INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
                             (group_id, json.dumps(data, ensure_ascii=False), now_str(), now_str()))
            by_name[data["name"]] = db.execute("SELECT * FROM candidates WHERE id=?", (cur.lastrowid,)).fetchone()
            created += 1

    gname = group_name_map().get(group_id, "")
    add_log(g.user, "import",
            f"{g.user['display_name']} 通过Excel向「{gname}」导入候选人：新增{created}人，更新{updated}人"
            + (f"，跳过{skipped}行" if skipped else ""),
            None, None, group_id)
    db.commit()
    return jsonify({"ok": True, "created": created, "updated": updated, "skipped": skipped})


# ---------------------------------------------------------------- 日志查询
@app.get("/api/logs")
@login_required
def api_logs():
    page = max(1, request.args.get("page", 1, type=int))
    size = 30
    db = get_db()
    where, params = "", []
    if g.user["role"] != "admin":
        where = "WHERE group_id=? OR group_id IS NULL"
        params.append(g.user["group_id"] or -1)
    total = db.execute(f"SELECT COUNT(*) AS c FROM logs {where}", params).fetchone()["c"]
    rows = db.execute(
        f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    ).fetchall()
    return jsonify({"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]})


# ---------------------------------------------------------------- 管理员总览
@app.get("/api/overview")
@admin_required
def api_overview():
    db = get_db()
    names = group_name_map()
    groups = []
    for gid, gname in names.items():
        rows = db.execute("SELECT * FROM candidates WHERE group_id=? ORDER BY updated_at DESC", (gid,)).fetchall()
        cands = []
        stats = {"total": len(rows), "signed": 0, "onboarded": 0, "high_risk": 0}
        for r in rows:
            c = candidate_dict(r, names)
            log = db.execute(
                "SELECT message, created_at FROM logs WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (r["id"],)
            ).fetchone()
            c["latest_log"] = (f"[{log['created_at']}] {log['message']}" if log else "暂无更新记录")
            cands.append(c)
            d = c["data"]
            if d.get("sign_status") == "已签约":
                stats["signed"] += 1
            if d.get("onboarded") == "是":
                stats["onboarded"] += 1
            if d.get("onboard_risk") == "高":
                stats["high_risk"] += 1
        groups.append({"group_id": gid, "group_name": gname, "stats": stats, "candidates": cands})
    return jsonify(groups)


# ---------------------------------------------------------------- 静态页面
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    init_db(demo="--demo" in sys.argv)
    port = int(os.environ.get("PORT", 8000))
    print(f"校招候选人管理系统已启动: http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
