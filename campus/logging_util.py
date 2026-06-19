# -*- coding: utf-8 -*-
"""应用日志配置。"""
import logging
import os
import sys

from campus.settings import BASE_DIR, load_app_config


def setup_logging():
    """运行日志写入 data/server.log 并同步输出控制台。"""
    app_cfg = load_app_config()
    level_name = os.environ.get("LOG_LEVEL") or app_cfg.get("logging", {}).get("level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    root = logging.getLogger("campus")
    root.setLevel(level)
    root.propagate = False
    if not root.handlers:
        fh = logging.FileHandler(os.path.join(BASE_DIR, "data", "server.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        if sys.stderr.isatty():
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            root.addHandler(sh)
    return root


log = setup_logging()


def who(user):
    """日志中标识操作用户。"""
    return f"{user['username']}({user['display_name']}/{user['role']})"
