@echo off
rem 重启服务（先优雅停止，失败则强杀，再后台启动）
cd /d %~dp0..
if exist venv\Scripts\python.exe (set "PY=venv\Scripts\python.exe") else (set "PY=python")
%PY% scripts\manage.py restart
