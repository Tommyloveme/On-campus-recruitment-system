#!/usr/bin/env bash
# 校招候选人管理系统 - Linux (SUSE 等) 启动脚本
set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}

if [ ! -d venv ]; then
    echo "[1/3] 创建 Python 虚拟环境..."
    "$PYTHON" -m venv venv
fi

echo "[2/3] 安装依赖..."
venv/bin/python -m pip install -q -r requirements.txt

echo "[3/3] 启动服务（首次运行会创建默认管理员 admin / admin123）..."
# 如需写入示例数据，运行: ./start.sh --demo
exec venv/bin/python app.py "$@"
