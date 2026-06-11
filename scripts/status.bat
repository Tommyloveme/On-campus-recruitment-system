@echo off
rem 查看服务运行状态（端口/PID/残留进程检测）
cd /d %~dp0..
if exist venv\Scripts\python.exe (set "PY=venv\Scripts\python.exe") else (set "PY=python")
%PY% scripts\manage.py status
