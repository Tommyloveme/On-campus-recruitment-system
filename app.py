# -*- coding: utf-8 -*-
"""校招全流程管理系统 - 跨平台（Windows / SUSE Linux）

覆盖登记、资审、笔试、技术面、主管面、报批、谈薪、Offer、入职九大流程。
技术栈：Flask + SQLite（标准库 sqlite3），Excel 导入使用 openpyxl。
各阶段字段通过 config/stages/<阶段>/fields.json 配置，公共字段在 config/stages/_common/fields.json。
"""
import os
import sys
import threading

from campus import create_app
from campus.core.logging_util import log
from campus.core.settings import APP_CONFIG
from campus.db.schema import init_db
from campus.services.backups import backup_scheduler

app = create_app()


def port_in_use(port):
    """Windows 下多个进程可同时绑定同一端口导致请求被旧实例接管，启动前先探测。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    init_db(demo="--demo" in sys.argv)
    port = int(os.environ.get("PORT", APP_CONFIG["server"]["port"]))
    threads = int(os.environ.get("THREADS", APP_CONFIG["server"]["threads"]))
    if port_in_use(port):
        log.error("端口 %d 已被占用，启动中止", port)
        print(f"错误：端口 {port} 已有服务在运行，请先停止旧实例（或修改 config/app_config.json 中的端口）。")
        sys.exit(1)
    threading.Thread(target=backup_scheduler, daemon=True).start()
    channel_timeout = int(os.environ.get(
        "CHANNEL_TIMEOUT",
        APP_CONFIG.get("server", {}).get("channel_timeout_sec", 1800)))
    log.info("服务启动 port=%d threads=%d log_level=%s upload_limit=%s channel_timeout=%ds",
             port, threads,
             os.environ.get("LOG_LEVEL") or APP_CONFIG.get("logging", {}).get("level", "INFO"),
             ("unlimited" if not APP_CONFIG.get("server", {}).get("max_upload_mb")
              else f"{APP_CONFIG.get('server', {}).get('max_upload_mb')}MB"),
             channel_timeout)
    print(f"校招全流程管理系统已启动: http://127.0.0.1:{port} （waitress，{threads} 工作线程）")
    from waitress import serve
    serve(app, host="0.0.0.0", port=port, threads=threads,
          connection_limit=1024, channel_timeout=channel_timeout)
