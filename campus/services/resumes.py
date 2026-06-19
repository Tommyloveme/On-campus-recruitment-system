# -*- coding: utf-8 -*-
import os
import secrets

from flask import g, jsonify

from campus.auth.permissions import can_delete_group, can_edit_group, can_view_group
from campus.db.connection import get_db
from campus.settings import RESUME_DIR


PREVIEW_PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>{title} - 简历预览</title>
<style>
body {{ font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:#f1f5f9; margin:0; }}
.page {{ max-width:860px; margin:24px auto; background:#fff; border-radius:12px;
        padding:40px 48px; box-shadow:0 4px 24px rgba(0,0,0,.08); line-height:1.8; color:#0f172a; }}
.page img {{ max-width:100%; }}
h1,h2,h3 {{ color:#1d4ed8; }}
table {{ border-collapse:collapse; }} td,th {{ border:1px solid #e2e8f0; padding:4px 10px; }}
.tip {{ text-align:center; color:#64748b; font-size:12px; margin:12px 0 24px; }}
</style></head><body>
<div class="tip">简历预览：{title}（如格式有出入，请下载原文件查看）</div>
<div class="page">{content}</div>
</body></html>"""


def remove_resume_file(stored_name):
    if not stored_name:
        return
    path = os.path.join(RESUME_DIR, stored_name)
    if os.path.exists(path):
        os.remove(path)


def get_candidate_or_403(cid, need="edit"):
    row = get_db().execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        return None, (jsonify({"error": "候选人不存在"}), 404)
    check = {"view": can_view_group, "edit": can_edit_group, "delete": can_delete_group}[need]
    if not check(g.user, row["group_id"]):
        return None, (jsonify({"error": "无该分组的操作权限"}), 403)
    return row, None


def new_resume_stored_name(cid, ext):
    return f"{cid}_{secrets.token_hex(8)}{ext}"
