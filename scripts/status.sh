#!/usr/bin/env bash
# 查看服务运行状态（端口/PID/残留进程检测）
cd "$(dirname "$0")/.."
PY=venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/manage.py status
