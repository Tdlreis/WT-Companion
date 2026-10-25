@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist data\aircraft.json (
  echo Montando o banco de avioes pela primeira vez...
  python build_db.py
)
python companion.py %*
pause
