@echo off
rem Rode depois de um patch grande do War Thunder (BRs e aviões novos).
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python build_db.py
pause
