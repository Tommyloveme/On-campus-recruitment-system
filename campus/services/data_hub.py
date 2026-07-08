# -*- coding: utf-8 -*-
"""数据汇总总表 data_hub（唯一写入口）。

把界面各子标签的编辑、主数据/Excel 导入的数据统一汇总为一张总表：
- 一级层级 source 区分数据来源（master_import 主数据导入 / manual 手动录入与
  页面编辑 / ui 界面专属列），避免同名字段混淆；
- 二级 tab_key 记录来源子标签（页面/阶段 key），同字段不同页面可快速检索；
- 统一优先使用「应聘档案编号」关联；手动登记无档案编号的候选人使用
  特殊键「无编号-<手机号>」，待主数据导入补齐应聘档案编号后自然并轨。
"""
from campus.db.connection import now_str
from campus.db.field_store import legacy_to_storage

SOURCE_MASTER = "master_import"
SOURCE_MANUAL = "manual"
SOURCE_UI = "ui"

NO_RESUME_PREFIX = "无编号-"


def hub_resume_key(data):
    """总表唯一化关联键：应聘档案编号 → 内部历史关联键 → 无编号-<手机号>。"""
    from campus.db.field_store import field_get
    for key in ("application_archive_id", "resume_id"):
        v = str(field_get(data, key) or "").strip()
        if v:
            return v
    phone = str(field_get(data, "phone") or "").strip()
    return f"{NO_RESUME_PREFIX}{phone}" if phone else ""


def record_hub_fields(db, source, tab_key, resume_key, fields,
                      label_map=None, user_name=""):
    """批量 UPSERT 总表行。fields: {field_key: value}；空 resume_key 跳过。"""
    if not resume_key:
        return 0
    label_map = label_map or {}
    now = now_str()
    n = 0
    for key, value in (fields or {}).items():
        if key.startswith("_"):
            continue
        sk = legacy_to_storage(key)
        db.execute(
            "INSERT INTO data_hub (source, tab_key, resume_id, field_key, field_label, "
            "value, updated_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source, tab_key, resume_id, field_key) DO UPDATE SET "
            "value=excluded.value, field_label=excluded.field_label, "
            "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (source, tab_key or "", resume_key, sk, label_map.get(key, label_map.get(sk, sk)),
             str(value if value is not None else ""), user_name, now, now),
        )
        n += 1
    return n


def query_hub(db, resume_id=None, source=None, tab=None, field=None, limit=2000):
    conds, args = [], []
    for col, val in (("resume_id", resume_id), ("source", source),
                     ("tab_key", tab), ("field_key", field)):
        if val:
            conds.append(f"{col}=?")
            args.append(val)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    rows = db.execute(
        f"SELECT * FROM data_hub{where} ORDER BY resume_id, source, tab_key, field_key LIMIT ?",
        args + [max(1, min(int(limit), 10000))],
    ).fetchall()
    return [dict(r) for r in rows]


def ui_values_for_tab(db, tab_key):
    """某子标签的 UI 专属列取值：{resume_key: {field_key: value}}。"""
    out = {}
    for r in db.execute(
        "SELECT resume_id, field_key, value FROM data_hub WHERE source=? AND tab_key=?",
        (SOURCE_UI, tab_key),
    ).fetchall():
        out.setdefault(r["resume_id"], {})[r["field_key"]] = r["value"]
    return out
