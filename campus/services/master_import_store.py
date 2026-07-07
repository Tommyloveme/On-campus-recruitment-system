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


def page_dir(page):
    return os.path.join(MASTER_DATA_DIR, page)


def meta_path(page):
    return os.path.join(page_dir(page), META_FILENAME)


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


def storage_path(page, source_cfg):
    name = source_cfg.get("storage_name") or f"{source_cfg['key']}.xlsx"
    return os.path.join(page_dir(page), name)


def save_upload(page, source_key, file_storage, original_filename, cfg):
    """保存上传文件并更新 meta；返回 (source_cfg, meta)。"""
    source = next((s for s in cfg["sources"] if s["key"] == source_key), None)
    if not source:
        raise ValueError(f"未知数据源: {source_key}")
    if not filename_matches(source_key, original_filename, cfg):
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
    files = get_stored_files(page, cfg)
    return all(files[k]["ready"] for k in cfg.get("source_keys", []))


def clear_page(page):
    d = page_dir(page)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
