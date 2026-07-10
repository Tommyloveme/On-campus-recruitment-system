# -*- coding: utf-8 -*-
"""应用日志配置：文件轮转 + 超限压缩归档。"""
import gzip
import logging
import os
import shutil
import sys
from logging.handlers import RotatingFileHandler

from campus.core.settings import BASE_DIR, load_app_config


class CompressedRotatingFileHandler(RotatingFileHandler):
    """达到 maxBytes 后轮转，并将旧日志 gzip 压缩。"""

    def rotation_filename(self, default_name):
        # RotatingFileHandler 生成 server.log.1 → 压缩为 server.log.1.gz
        if default_name.endswith(".gz"):
            return default_name
        return default_name + ".gz"

    def rotate(self, source, dest):
        if os.path.exists(source):
            with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            try:
                os.remove(source)
            except OSError:
                pass


def setup_logging():
    """运行日志写入 data/server.log，超限轮转并 gzip；TTY 下同步控制台。"""
    app_cfg = load_app_config()
    log_cfg = app_cfg.get("logging") or {}
    level_name = os.environ.get("LOG_LEVEL") or log_cfg.get("level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    max_mb = float(log_cfg.get("max_bytes_mb", 10) or 10)
    backup_count = int(log_cfg.get("backup_count", 5) or 5)
    max_bytes = max(1, int(max_mb * 1024 * 1024))

    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    log_path = os.path.join(data_dir, "server.log")

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    root = logging.getLogger("campus")
    root.setLevel(level)
    root.propagate = False

    # 热重载 / 重复 import 时避免重复 handler
    if not root.handlers:
        fh = CompressedRotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        if sys.stderr.isatty():
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            root.addHandler(sh)
    else:
        root.setLevel(level)

    return root


log = setup_logging()


def who(user):
    """日志中标识操作用户。"""
    if not user:
        return "-"
    try:
        return f"{user['username']}({user['display_name']}/{user['role']})"
    except (TypeError, KeyError):
        return str(user)
