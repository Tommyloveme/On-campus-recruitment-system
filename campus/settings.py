# -*- coding: utf-8 -*-
"""运行路径与配置加载（与业务逻辑解耦）。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DB_PATH = os.path.join(BASE_DIR, "data", "candidates.db")
APP_CONFIG_PATH = os.path.join(CONFIG_DIR, "app_config.json")
SECRET_PATH = os.path.join(BASE_DIR, "data", ".secret_key")
RESUME_DIR = os.path.join(BASE_DIR, "data", "resumes")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")


def load_app_config():
    """运行配置（config/app_config.json）：端口、线程数、分页大小等。"""
    with open(APP_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


APP_CONFIG = load_app_config()
ALLOWED_RESUME_EXT = set(APP_CONFIG["resume"]["allowed_ext"])
