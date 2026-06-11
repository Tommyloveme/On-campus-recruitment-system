#!/usr/bin/env bash
# 重启服务（先优雅停止，失败则强杀，再后台启动）
cd "$(dirname "$0")/.."
PY=venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" scripts/manage.py restart
