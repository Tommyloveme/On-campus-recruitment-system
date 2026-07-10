# -*- coding: utf-8 -*-
"""主数据表文件存储与元数据（上传暂存，刷新时合并写入候选人）。"""
import fnmatch
import json
import os
import shutil
from datetime import datetime

from campus.core.settings import BASE_DIR

MASTER_DATA_DIR = os.path.join(BASE_DIR, "data", "master_import")
META_FILENAME = "meta.json"
PROGRESS_FILENAME = "progress.json"


def page_dir(page):
    return os.path.join(MASTER_DATA_DIR, page)


def meta_path(page):
    return os.path.join(page_dir(page), META_FILENAME)


def progress_path(page):
    return os.path.join(page_dir(page), PROGRESS_FILENAME)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_meta(page):
    path = meta_path(page)
    if not os.path.exists(path):
        return {"page": page, "files": {}, "last_refresh": None, "last_refresh_stats": None}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_meta(page, meta):
    os.makedirs(page_dir(page), exist_ok=True)
    with open(meta_path(page), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_progress(page):
    path = progress_path(page)
    if not os.path.exists(path):
        return {
            "page": page,
            "status": "idle",
            "phase": "",
            "message": "",
            "percent": 0,
            "current": 0,
            "total": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "error": None,
            "updated_at": None,
        }
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"page": page, "status": "idle", "percent": 0, "message": ""}


def save_progress(page, **fields):
    """写入导入进度（独立文件，供前端轮询；不依赖 DB 事务）。"""
    os.makedirs(page_dir(page), exist_ok=True)
    cur = load_progress(page)
    cur.update(fields)
    cur["page"] = page
    cur["updated_at"] = _now()
    path = progress_path(page)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False)
    os.replace(tmp, path)
    return cur


def clear_progress(page):
    path = progress_path(page)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def filename_matches(source_key, original_name, cfg):
    patterns = cfg.get("file_patterns") or {}
    pattern = patterns.get(source_key, "*")
    name = original_name or ""
    return fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.lower(), pattern.lower())


def detect_source_key(original_name, cfg):
    for key in cfg.get("source_keys", []):
        if filename_matches(key, original_name, cfg):
            return key
    return None


def detect_source_key_by_headers(header_row, cfg):
    """按表头特征识别数据源（文件名不匹配时的兜底）。"""
    headers = {str(h or "").strip() for h in (header_row or []) if str(h or "").strip()}
    if not headers:
        return None
    keys = set(cfg.get("source_keys") or [])
    if "interview_mgmt" in keys and (
            {"应聘档案编号", "候选人姓名"} <= headers or {"应聘档案编号", "面试进展"} <= headers):
        return "interview_mgmt"
    if {"简历编号", "姓名", "联系电话"} <= headers or {"简历编号", "应聘档案编号"} <= headers:
        return "application"
    return None


def storage_path(page, source_cfg):
    name = source_cfg.get("storage_name") or f"{source_cfg['key']}.xlsx"
    return os.path.join(page_dir(page), name)


def save_upload(page, source_key, file_storage, original_filename, cfg, enforce_pattern=True):
    """保存上传文件并更新 meta；返回 (source_cfg, meta)。

    enforce_pattern=False 用于表头特征识别成功但文件名不符合模式的场景。
    """
    source = next((s for s in cfg["sources"] if s["key"] == source_key), None)
    if not source:
        raise ValueError(f"未知数据源: {source_key}")
    if enforce_pattern and not filename_matches(source_key, original_filename, cfg):
        pattern = (cfg.get("file_patterns") or {}).get(source_key, "*")
        raise ValueError(f"文件名「{original_filename}」不匹配要求：{pattern}")

    os.makedirs(page_dir(page), exist_ok=True)
    dest = storage_path(page, source)
    file_storage.save(dest)

    meta = load_meta(page)
    meta.setdefault("files", {})[source_key] = {
        "original_name": original_filename,
        "storage_name": os.path.basename(dest),
        "uploaded_at": _now(),
        "uploaded_by": None,
    }
    save_meta(page, meta)
    return source, meta


def get_stored_files(page, cfg):
    """返回各数据源是否已上传及路径。"""
    meta = load_meta(page)
    result = {}
    for source in cfg.get("sources", []):
        key = source["key"]
        path = storage_path(page, source)
        info = meta.get("files", {}).get(key)
        result[key] = {
            "key": key,
            "label": source.get("label", key),
            "pattern": (cfg.get("file_patterns") or {}).get(key, "*"),
            "ready": os.path.isfile(path),
            "original_name": info.get("original_name") if info else None,
            "uploaded_at": info.get("uploaded_at") if info else None,
            "path": path if os.path.isfile(path) else None,
        }
    return result


def both_files_ready(page, cfg):
    """任一数据表就绪即可刷新（支持单表单独上传后刷新，按唯一键合并）。"""
    files = get_stored_files(page, cfg)
    keys = cfg.get("source_keys") or []
    return any(files.get(k, {}).get("ready") for k in keys)


def clear_page(page):
    d = page_dir(page)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
