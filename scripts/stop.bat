@echo off
rem 停止服务（按端口定位进程）
cd /d %~dp0..
if exist venv\Scripts\python.exe (set "PY=venv\Scripts\python.exe") else (set "PY=python")
%PY% scripts\manage.py stop
