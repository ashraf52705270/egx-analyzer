@echo off
:: تشغيل EGX Analyzer تلقائياً مع Windows
cd /d "%~dp0"
start /b /min "" python main.py
timeout /t 5 /nobreak >nul
start /b /min "" cloudflared.exe tunnel --url http://localhost:8000 > tunnel.log 2>&1
timeout /t 15 /nobreak >nul
:: حفظ الرابط
powershell -Command "Select-String -Path tunnel.log -Pattern 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' | Select-Object -First 1 -ExpandProperty Matches | ForEach-Object { $_.Value } | Set-Content tunnel_url.txt"
echo ----------------------------------------
echo تم التشغيل. الرابط في tunnel_url.txt
echo ----------------------------------------
pause