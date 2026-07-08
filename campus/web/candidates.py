# -*- coding: utf-8 -*-
"""候选人 CRUD 与批量操作。"""
import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from campus.core.logging_util import log, who
from campus.core.stage_config import editable_fields, field_labels, get_stage_meta, validate_stage
from campus.db.connection import get_db
from campus.db.field_store import field_get, field_set
from campus.domain.stage_routing import compute_current_stage
from campus.services.acl import (
    can_delete_candidate,
    can_edit_candidate,
    can_see_candidate,
    is_admin,
    module_writable_for,
)
from campus.services.audit import add_log
from campus.services.candidate_pipeline import delete_raw_records, record_manual
from campus.services.data_hub import SOURCE_MANUAL, hub_resume_key, record_hub_fields
from campus.services.candidates import (
    PhoneDuplicateError,
    candidate_dict,
    delete_candidate_row,
    find_candidate_by_phone,
    group_name_map,
    insert_candidate_row,
    merge_candidate_rows,
    normalize_candidate_phone,
    phone_duplicate_payload,
    update_candidate_row,
)
from campus.services.users import (
    apply_registration_candidate_defaults,
    apply_registration_employee_fields,
    validate_registration_manual_create,
    validate_registration_user_refs,
)
from campus.web.guards import login_required

bp = Blueprint("candidates", __name__)


@bp.get("/api/candidates")
@login_required
def api_candidates():
    db = get_db()
    rows = db.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    # 共享池：所有登录用户可见
    rows = [r for r in rows if can_see_candidate(db, g.user, r)]
    names = group_name_map()
    result = [candidate_dict(r, names) for r in rows]
    q = (request.args.get("q") or "").strip()
    stage_filter = request.args.get("stage")
    if q:
        result = [c for c in result if any(q in str(v) for v in c["data"].values())]
    if stage_filter:
        result = [c for c in result if (c.get("current_stage")
                  or field_get(c["data"], "current_stage")) == stage_filter]
    log.debug("候选人列表 %s 返回%d条 q=%s stage=%s",
              who(g.user), len(result), q or "-", stage_filter or "-")
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
    # 模块级写权限：阶段 key 即模块 key，须具备写权限
    if not module_writable_for(g.user, stage):
        log.warning("新增候选人模块写权限拒绝 %s stage=%s", who(g.user), stage)
        return jsonify({"error": f"无「{meta['label']}」模块的写入权限"}), 403
    # 共享池：候选人不再归属资源分组
    group_id = None
    fields = editable_fields(stage)
    incoming = b.get("data", {})
    data = {}
    for f in fields:
        raw = incoming.get(f["key"], incoming.get(f.get("legacy_key", ""), ""))
        data[f["key"]] = str(raw or "").strip()
    if not field_get(data, "name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400

    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if stage == "registration":
        if not field_get(data, "registration_time"):
            field_set(data, "registration_time", today)
        if not field_get(data, "registration_status"):
            field_set(data, "registration_status", "待投递")
        data = apply_registration_candidate_defaults(data, g.user)
        missing = validate_registration_manual_create(data)
        if missing:
            return jsonify({"error": f"请填写：{'、'.join(missing)}"}), 400
        ref_err = validate_registration_user_refs(
            db, field_get(data, "sourcer"), field_get(data, "interface_person"))
        if ref_err:
            return jsonify({"error": ref_err, "code": "user_not_registered"}), 400
        data = apply_registration_employee_fields(db, data)

    phone = normalize_candidate_phone(field_get(data, "phone"))
    if not phone:
        return jsonify({"error": "电话不能为空，候选人以电话作为唯一标识"}), 400
    field_set(data, "phone", phone)
    dup = find_candidate_by_phone(db, phone)
    if dup:
        return jsonify(phone_duplicate_payload(db, dup, phone)), 409

    compute_current_stage(data)
    try:
        cid = insert_candidate_row(db, data, group_id=group_id)
    except PhoneDuplicateError as e:
        return jsonify(e.payload), 409
    record_manual(db, phone, data)
    record_hub_fields(db, SOURCE_MANUAL, stage, hub_resume_key(data),
                      {k: v for k, v in data.items() if v},
                      field_labels(stage), g.user["display_name"])
    cand_name = field_get(data, "name")
    add_log(g.user, "create", f"{g.user['display_name']} 在{meta['label']}新增了候选人「{cand_name}」",
            cid, cand_name, module=stage)
    db.commit()
    log.info("新增候选人 %s id=%d name=%s stage=%s phone=%s", who(g.user), cid, cand_name, stage, phone)
    return jsonify({"ok": True, "id": cid})


@bp.put("/api/candidates/<int:cid>")
@login_required
def api_candidate_update(cid):
    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404
    if not can_edit_candidate(db, g.user, row):
        log.warning("修改候选人权限拒绝 %s cid=%d", who(g.user), cid)
        return jsonify({"error": "无该候选人的编辑权限"}), 403
    b = request.get_json(force=True)
    old = json.loads(row["data"])
    incoming = b.get("data", {})
    stage = b.get("stage") or request.args.get("stage", "registration")
    try:
        validate_stage(stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # 模块级写权限：当前编辑阶段 key 即模块 key
    if not module_writable_for(g.user, stage):
        log.warning("修改候选人模块写权限拒绝 %s cid=%d stage=%s", who(g.user), cid, stage)
        return jsonify({"error": f"无「{get_stage_meta(stage)['label']}」模块的写入权限"}), 403
    fields = editable_fields(stage)
    labels = field_labels(stage)
    new = dict(old)
    locked = set(field_get(old, "_master_locked_fields") or [])
    changes = []
    changed_keys = []
    blocked = []
    for f in fields:
        k = f["key"]
        leg = f.get("legacy_key") or k
        if k in incoming:
            raw = incoming[k]
        elif leg in incoming:
            raw = incoming[leg]
        else:
            continue
        nv = str(raw or "").strip()
        ov = str(field_get(old, k, "") or "")
        if nv == ov:
            continue
        if k in locked or leg in locked:
            blocked.append(labels.get(k, k))
            continue
        field_set(new, k, nv)
        changed_keys.append(k)
        changes.append(f"{labels[k]}：{ov or '空'} → {nv or '空'}")
    if blocked:
        return jsonify({
            "error": f"以下字段已由主数据表锁定，不可修改：{'、'.join(blocked)}",
            "code": "master_locked",
            "locked_fields": list(locked),
        }), 400
    if not changes:
        return jsonify({"ok": True, "changed": 0})
    if not field_get(new, "name"):
        return jsonify({"error": "候选人姓名不能为空"}), 400
    phone = normalize_candidate_phone(field_get(new, "phone"))
    if not phone:
        return jsonify({"error": "电话不能为空，候选人以电话作为唯一标识"}), 400
    field_set(new, "phone", phone)
    dup = find_candidate_by_phone(db, phone, exclude_id=cid)
    if dup:
        if not b.get("merge_on_conflict"):
            payload = phone_duplicate_payload(db, dup, phone)
            payload["can_merge"] = True
            return jsonify(payload), 409
        # 双手机号同一人：确认合并（主数据侧数据优先，保留主数据侧行）
        merged_id, merged = merge_candidate_rows(db, row, new, dup)
        name = field_get(merged, "name")
        add_log(g.user, "update",
                f"{g.user['display_name']} 通过修改电话合并了候选人「{name}」的两条记录"
                f"（保留 #{merged_id}，主数据优先）",
                merged_id, name, module=stage)
        db.commit()
        log.info("电话合并 %s keep=%d drop=%d phone=%s", who(g.user), merged_id, cid, phone)
        return jsonify({"ok": True, "merged": True, "id": merged_id})
    if stage == "registration":
        ref_err = validate_registration_user_refs(
            db, field_get(new, "sourcer"), field_get(new, "interface_person"))
        if ref_err:
            return jsonify({"error": ref_err, "code": "user_not_registered"}), 400
        new = apply_registration_employee_fields(db, new)
    for k, v in old.items():
        if k not in new:
            new[k] = v
    compute_current_stage(new)
    try:
        update_candidate_row(db, cid, new)
    except PhoneDuplicateError as e:
        return jsonify(e.payload), 409
    old_phone = normalize_candidate_phone(field_get(old, "phone"))
    if old_phone and old_phone != phone:
        delete_raw_records(db, old_phone)
    record_manual(db, phone, new)
    record_hub_fields(db, SOURCE_MANUAL, stage, hub_resume_key(new),
                      {k: new[k] for k in changed_keys},
                      labels, g.user["display_name"])
    name = field_get(new, "name") or field_get(old, "name")
    add_log(g.user, "update",
            f"{g.user['display_name']} 修改了「{name}」：" + "；".join(changes),
            cid, name, row["group_id"], module=stage)
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
    if not can_delete_candidate(db, g.user, row):
        log.warning("删除候选人权限拒绝 %s cid=%d", who(g.user), cid)
        return jsonify({"error": "无删除权限（需对候选人当前阶段模块具备写权限）"}), 403
    name = field_get(json.loads(row["data"]), "name")
    delete_candidate_row(db, row)
    add_log(g.user, "delete", f"{g.user['display_name']} 删除了候选人「{name}」", cid, name, row["group_id"],
            module=request.args.get("stage") or "registration")
    db.commit()
    log.info("删除候选人 %s id=%d name=%s", who(g.user), cid, name)
    return jsonify({"ok": True})


@bp.post("/api/candidates/batch_delete")
@login_required
def api_candidates_batch_delete():
    if not is_admin(g.user):
        log.warning("批量删除权限拒绝 %s", who(g.user))
        return jsonify({"error": "仅系统管理员可批量删除"}), 403
    ids = request.get_json(force=True).get("ids") or []
    if not ids:
        return jsonify({"error": "请先勾选候选人"}), 400
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()

    deleted_names = []
    for row in rows:
        if not can_delete_candidate(db, g.user, row):
            continue
        delete_candidate_row(db, row)
        deleted_names.append(field_get(json.loads(row["data"]), "name"))
    if not deleted_names:
        return jsonify({"error": "选中的候选人均无删除权限"}), 403

    shown = "、".join(deleted_names[:5]) + ("等" if len(deleted_names) > 5 else "")
    add_log(g.user, "delete",
            f"{g.user['display_name']} 批量删除了 {len(deleted_names)} 名候选人（{shown}）",
            group_id=g.user["group_id"], module="registration")
    db.commit()
    log.info("批量删除 %s 删除%d 跳过%d", who(g.user), len(deleted_names), len(rows) - len(deleted_names))
    return jsonify({"ok": True, "deleted": len(deleted_names),
                    "skipped": len(rows) - len(deleted_names)})


@bp.post("/api/candidates/<int:cid>/stage-transition")
@login_required
def api_candidate_stage_transition(cid):
    """Offer 策略手动流转：direction=next（下一流程）/ prev（退回）/ auto（恢复自动判定）。

    仅 config/stage_flow.json 配置的角色（或管理员）可操作，且候选人当前
    须处于配置的阶段范围内。切换写入 manual_stage，优先于自动判定。
    """
    from campus.core.stage_flow import load_stage_flow
    from campus.domain.stage_routing import (
        MANUAL_STAGE_KEY,
        OFFER_STRATEGY_STAGES,
        manager_interview_passed,
        ordered_stage_keys,
        stage_label_map,
    )
    from campus.services.acl import manual_transition_allowed

    if not manual_transition_allowed(g.user):
        log.warning("手动流转权限拒绝 %s cid=%d", who(g.user), cid)
        return jsonify({"error": "无手动流转权限（角色可在 config/stage_flow.json 配置）"}), 403

    db = get_db()
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "候选人不存在"}), 404

    direction = (request.get_json(force=True) or {}).get("direction", "")
    if direction not in ("next", "prev", "auto"):
        return jsonify({"error": "direction 须为 next / prev / auto"}), 400

    data = json.loads(row["data"])
    flow = load_stage_flow()
    current = field_get(data, "current_stage") or "registration"
    if current not in flow["stages"]:
        return jsonify({"error": f"当前阶段「{current}」不支持手动流转（配置见 config/stage_flow.json）"}), 400

    labels = stage_label_map()
    if direction == "auto":
        data.pop(MANUAL_STAGE_KEY, None)
        data.pop("_手动流程阶段", None)
        detail = "恢复自动判定"
    else:
        order = ordered_stage_keys()
        idx = order.index(current) if current in order else -1
        target_idx = idx + (1 if direction == "next" else -1)
        if idx < 0 or not 0 <= target_idx < len(order):
            return jsonify({"error": "已到流程边界，无法继续流转"}), 400
        target = order[target_idx]
        if target in OFFER_STRATEGY_STAGES and not manager_interview_passed(data):
            return jsonify({
                "error": "主管面未通过，不可进入 Offer 策略流程（报批/谈薪/Offer/签约）",
                "code": "manager_interview_required",
            }), 400
        field_set(data, MANUAL_STAGE_KEY, target)
        detail = f"{labels.get(current, current)} → {labels.get(target, target)}"

    compute_current_stage(data)
    update_candidate_row(db, cid, data)
    record_manual(db, normalize_candidate_phone(field_get(data, "phone")), data)
    name = field_get(data, "name")
    add_log(g.user, "update",
            f"{g.user['display_name']} 手动流转候选人「{name}」：{detail}",
            cid, name, module=current)
    db.commit()
    log.info("手动流转 %s cid=%d %s", who(g.user), cid, detail)
    return jsonify({"ok": True, "current_stage": field_get(data, "current_stage"),
                    "manual_stage": field_get(data, MANUAL_STAGE_KEY, "")})


@bp.post("/api/candidates/recompute-stages")
@login_required
def api_recompute_stages():
    if not is_admin(g.user):
        return jsonify({"error": "仅系统管理员可执行"}), 403
    db = get_db()
    rows = db.execute("SELECT * FROM candidates").fetchall()
    n = 0
    for row in rows:
        data = json.loads(row["data"])
        old = field_get(data, "current_stage")
        compute_current_stage(data)
        if field_get(data, "current_stage") != old:
            update_candidate_row(db, row["id"], data)
            n += 1
    add_log(g.user, "config", f"{g.user['display_name']} 重算了 {n} 名候选人的当前流程阶段")
    db.commit()
    return jsonify({"ok": True, "updated": n})
