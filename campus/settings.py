# -*- coding: utf-8 -*-
"""运行路径与配置加载（与业务逻辑解耦）。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DB_PATH = os.path.join(BASE_DIR, "data", "candidates.db")
APP_CONFIG_PATH = os.path.join(CONFIG_DIR, "app_config.json")
USER_FIELDS_PATH = os.path.join(CONFIG_DIR, "user_fields.json")
ROLES_PATH = os.path.join(CONFIG_DIR, "roles.json")
SECRET_PATH = os.path.join(BASE_DIR, "data", ".secret_key")
RESUME_DIR = os.path.join(BASE_DIR, "data", "resumes")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
FEEDBACK_DIR = os.path.join(BASE_DIR, "data", "feedback_images")


def load_app_config():
    """运行配置（config/app_config.json）：端口、线程数、分页大小等。"""
    with open(APP_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_user_fields():
    """用户附属信息字段配置（config/user_fields.json）。"""
    try:
        with open(USER_FIELDS_PATH, encoding="utf-8") as f:
            return json.load(f).get("fields", [])
    except (OSError, json.JSONDecodeError):
        return []


APP_CONFIG = load_app_config()
USER_FIELDS = load_user_fields()
ALLOWED_RESUME_EXT = set(APP_CONFIG["resume"]["allowed_ext"])
