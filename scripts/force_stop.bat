@echo off
rem 强制停止：杀掉端口进程 + 所有 app.py 残留进程（WAL 模式数据安全）
cd /d %~dp0..
if exist venv\Scripts\python.exe (set "PY=venv\Scripts\python.exe") else (set "PY=python")
%PY% scripts\manage.py force_stop
