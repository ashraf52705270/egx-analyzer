@echo off
cd /d "%~dp0"
start /b /min "" python main.py
timeout /t 4 /nobreak >nul
start "" http://localhost:8000
