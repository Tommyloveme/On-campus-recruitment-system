# -*- coding: utf-8 -*-
"""候选人 CRUD 与批量操作。"""
import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from campus.auth.decorators import login_required
from campus.auth.permissions import can_delete_group, can_edit_group
from campus.config_loader import editable_fields, field_labels, get_stage_meta, validate_stage
from campus.db.connection import get_db, now_str
from campus.logging_util import log, who
from campus.services.audit import add_log
from campus.services.candidates import candidate_dict, group_name_map
from campus.services.users import (
    apply_registration_candidate_defaults,
    validate_registration_manual_create,
    validate_registration_user_refs,
)
from campus.services.resumes import remove_resume_file
from campus.stage_engine import compute_current_stage, merge_candidate_data, build_global_candidate_index

bp = Blueprint("candidates", __name__)


@bp.get("/api/candidates")
@login_required
def api_candidates():
    db = get_db()
    rows = db.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    names = group_name_map()
    result = [candidate_dict(r, names) for r in rows]
    q = (request.args.get("q") or "").strip()
    stage_filter = request.args.get("stage")
    if q:
        result = [c for c in result if any(q in str(v) for v in c["data"].values())]
    if stage_filter:
        result = [c for c in result if c["data"].get("current_stage") == stage_filter]
    log.debug("候选人列表 %s 返回%d条 q=%s group=%s stage=%s",
              who(g.user), len(result), q or "-", request.args.get("group_id", "-"), stage_filter or "-")
    return jsonify(result)


@bp.post("/api/candidates")
@login_required
def api_candidate_create():
    b = request.get_json(force=True)
    stage = b.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    meta = get_stage_meta(stage)
    if not meta.get("can_create"):
        return jsonify({"error": f"「{meta['label']}」阶段不支持新增候选人，请在登记阶段新增"}), 400
    if not can_edit_group(g.user):
        log.warning("新增候选人权限拒绝 %s", who(g.user))
        return jsonify({"error": "无新增候选人权限"}), 403
    group_id = None
    fields = editable_fields(stage)
    data = {f["key"]: str(b.get("data", {}).get(f["key"], "") or "").strip() for f in fields}
    if not data.get("name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400

    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if stage == "registration":
        if not data.get("registration_time"):
            data["registration_time"] = today
        if not data.get("registration_status"):
            data["registration_status"] = "待投递"
        data = apply_registration_candidate_defaults(data, g.user)
        missing = validate_registration_manual_create(data)
        if missing:
            return jsonify({"error": f"请填写：{'、'.join(missing)}"}), 400
        ref_err = validate_registration_user_refs(db, data.get("sourcer"), data.get("interface_person"))
        if ref_err:
            return jsonify({"error": ref_err, "code": "user_not_registered"}), 400

    phone = data.get("phone", "").strip()
    confirm_overwrite = bool(b.get("confirm_overwrite"))

    # 登记阶段：同手机号须用户确认后才覆盖已有候选人
    if stage == "registration" and phone:
        _, by_phone, _ = build_global_candidate_index(db)
        match = by_phone.get(phone)
        if match and can_edit_group(g.user):
            old = json.loads(match["data"])
            if not confirm_overwrite:
                return jsonify({
                    "error": "该手机号已存在",
                    "code": "phone_duplicate",
                    "existing": {
                        "id": match["id"],
                        "name": old.get("name") or "",
                        "phone": phone,
                        "sourcer": old.get("sourcer") or "",
                        "interface_person": old.get("interface_person") or "",
                    },
                }), 409
            merged = merge_candidate_data(old, data)
            merged["registration_time"] = data.get("registration_time") or today
            if not str(old.get("registration_status") or "").strip():
                merged["registration_status"] = data.get("registration_status", "待投递")
            compute_current_stage(merged)
            db.execute(
                "UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), now_str(), match["id"]),
            )
            name = merged.get("name") or old.get("name", "")
            add_log(g.user, "update",
                    f"{g.user['display_name']} 登记覆盖了候选人「{name}」（电话 {phone}）",
                    match["id"], name)
            db.commit()
            log.info("登记覆盖 %s id=%d phone=%s", who(g.user), match["id"], phone)
            return jsonify({"ok": True, "id": match["id"], "overwritten": True})

    compute_current_stage(data)
    cur = db.execute(
        "INSERT INTO candidates (group_id, data, created_at, updated_at) VALUES (?,?,?,?)",
        (group_id, json.dumps(data, ensure_ascii=False), now_str(), now_str()),
    )
    add_log(g.user, "create", f"{g.user['display_name']} 在{meta['label']}新增了候选人「{data['name']}」",
            cur.lastrowid, data["name"])
    db.commit()
    log.info("新增候选人 %s id=%d name=%s stage=%s", who(g.user), cur.lastrowid, data["name"], stage)
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.put("/api/candidates/<int:cid>")
@login_required
def api_candidate_update(cid):
    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_group(g.user, row["group_id"]):
        log.warning("修改候选人权限拒绝 %s cid=%d", who(g.user), cid)
        return jsonify({"error": "无该分组的编辑权限"}), 403
    b = request.get_json(force=True)
    old = json.loads(row["data"])
    incoming = b.get("data", {})
    stage = b.get("stage") or request.args.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    fields = editable_fields(stage)
    labels = field_labels(stage)
    new = dict(old)
    locked = set(old.get("_master_locked_fields") or [])
    changes = []
    blocked = []
    for f in fields:
        if f["key"] not in incoming:
            continue
        k = f["key"]
        nv = str(incoming[k] or "").strip()
        ov = str(old.get(k, "") or "")
        if nv == ov:
            continue
        if k in locked:
            blocked.append(labels.get(k, k))
            continue
        new[k] = nv
        changes.append(f"{labels[k]}：{ov or '空'} → {nv or '空'}")
    if blocked:
        return jsonify({
            "error": f"以下字段已由主数据表锁定，不可修改：{'、'.join(blocked)}",
            "code": "master_locked",
            "locked_fields": list(locked),
        }), 400
    if not changes:
        return jsonify({"ok": True, "changed": 0})
    if not new.get("name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400
    if stage == "registration":
        ref_err = validate_registration_user_refs(db, new.get("sourcer"), new.get("interface_person"))
        if ref_err:
            return jsonify({"error": ref_err, "code": "user_not_registered"}), 400
    for k, v in old.items():
        if k not in new:
            new[k] = v
    compute_current_stage(new)
    db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
               (json.dumps(new, ensure_ascii=False), now_str(), cid))
    name = new.get("name") or old.get("name", "")
    add_log(g.user, "update",
            f"{g.user['display_name']} 修改了「{name}」：" + "；".join(changes),
            cid, name, row["group_id"])
    db.commit()
    log.info("修改候选人 %s id=%d name=%s 变更%d项", who(g.user), cid, name, len(changes))
    log.debug("修改明细 id=%d %s", cid, "；".join(changes))
    return jsonify({"ok": True, "changed": len(changes)})


@bp.delete("/api/candidates/<int:cid>")
@login_required
def api_candidate_delete(cid):
    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_delete_group(g.user, row["group_id"]):
        log.warning("删除候选人权限拒绝 %s cid=%d", who(g.user), cid)
        return jsonify({"error": "无删除权限（仅系统管理员和组管理员可删除）"}), 403
    name = json.loads(row["data"]).get("name", "")
    remove_resume_file(row["resume_file"])
    db.execute("DELETE FROM candidates WHERE id=?", (cid,))
    add_log(g.user, "delete", f"{g.user['display_name']} 删除了候选人「{name}」", cid, name, row["group_id"])
    db.commit()
    log.info("删除候选人 %s id=%d name=%s", who(g.user), cid, name)
    return jsonify({"ok": True})


@bp.post("/api/candidates/batch_delete")
@login_required
def api_candidates_batch_delete():
    if g.user["role"] not in ("admin", "group_admin"):
        log.warning("批量删除权限拒绝 %s", who(g.user))
        return jsonify({"error": "仅系统管理员和组管理员可批量删除"}), 403
    ids = request.get_json(force=True).get("ids") or []
    if not ids:
        return jsonify({"error": "请先勾选候选人"}), 400
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()

    deleted_names = []
    for row in rows:
        if not can_delete_group(g.user, row["group_id"]):
            continue
        remove_resume_file(row["resume_file"])
        db.execute("DELETE FROM candidates WHERE id=?", (row["id"],))
        deleted_names.append(json.loads(row["data"]).get("name", ""))
    if not deleted_names:
        return jsonify({"error": "选中的候选人均无删除权限"}), 403

    shown = "、".join(deleted_names[:5]) + ("等" if len(deleted_names) > 5 else "")
    add_log(g.user, "delete",
            f"{g.user['display_name']} 批量删除了 {len(deleted_names)} 名候选人（{shown}）",
            group_id=g.user["group_id"])
    db.commit()
    log.info("批量删除 %s 删除%d 跳过%d", who(g.user), len(deleted_names), len(rows) - len(deleted_names))
    return jsonify({"ok": True, "deleted": len(deleted_names),
                    "skipped": len(rows) - len(deleted_names)})


@bp.post("/api/candidates/recompute-stages")
@login_required
def api_recompute_stages():
    if g.user["role"] not in ("admin", "group_admin"):
        return jsonify({"error": "无权限"}), 403
    db = get_db()
    rows = db.execute("SELECT * FROM candidates").fetchall()
    n = 0
    for row in rows:
        data = json.loads(row["data"])
        old = data.get("current_stage")
        compute_current_stage(data)
        if data.get("current_stage") != old:
            db.execute("UPDATE candidates SET data=?, updated_at=? WHERE id=?",
                       (json.dumps(data, ensure_ascii=False), now_str(), row["id"]))
            n += 1
    add_log(g.user, "config", f"{g.user['display_name']} 重算了 {n} 名候选人的当前流程阶段")
    db.commit()
    return jsonify({"ok": True, "updated": n})
