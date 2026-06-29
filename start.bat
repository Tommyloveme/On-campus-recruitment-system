@echo off
rem 校招入职跟踪管理系统 - Windows 启动脚本
chcp 65001 >nul
cd /d "%~dp0"

if not exist venv (
    echo [1/3] 创建 Python 虚拟环境...
    python -m venv venv || (echo 创建虚拟环境失败，请确认已安装 Python 3.9+ && pause && exit /b 1)
)

echo [2/3] 安装依赖...
venv\Scripts\python -m pip install -q -r requirements.txt || (echo 依赖安装失败 && pause && exit /b 1)

echo [3/3] 启动服务（首次运行会创建默认管理员 admin / admin123）...
rem 若端口已被旧实例占用，先停止再启动（避免“端口已占用”导致无法启动）
venv\Scripts\python scripts\manage.py stop >nul 2>&1
rem 如需写入示例数据，改为: venv\Scripts\python app.py --demo
venv\Scripts\python app.py %*
pause
