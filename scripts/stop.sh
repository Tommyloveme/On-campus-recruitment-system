#!/usr/bin/env bash
# 停止服务（SIGTERM 优雅退出，按端口定位进程）
cd "$(dirname "$0")/.."
PY=venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/manage.py stop
