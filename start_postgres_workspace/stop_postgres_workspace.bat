@echo off
setlocal
cd /d "%~dp0"
py "%~dp0stop_postgres_workspace.py"
pause
