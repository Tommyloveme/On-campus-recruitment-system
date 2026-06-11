#!/usr/bin/env bash
# 强制停止：SIGKILL 端口进程 + 所有 app.py 残留进程（WAL 模式数据安全）
cd "$(dirname "$0")/.."
PY=venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/manage.py force_stop
