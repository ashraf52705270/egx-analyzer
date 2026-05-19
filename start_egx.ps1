# Script تشغيل EGX Analyzer (يعمل في الخلفية — بدون نافذة)
$dir = "C:\Users\ashra\OneDrive\Desktop\New folder"
$ws = New-Object -ComObject WScript.Shell

# قتل أي عمليات قديمة
Get-Process -Name python, cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# تشغيل السيرفر (مخفي)
$ws.Run("cmd /c ""cd /d $dir && python main.py""", 0, $false)
Start-Sleep -Seconds 4

# تشغيل الـ tunnel (مخفي)
$tunnelLog = Join-Path $dir "tunnel.log"
$ws.Run("cmd /c ""`"$dir\cloudflared.exe`" tunnel --url http://localhost:8000 > `"$tunnelLog`" 2>&1""", 0, $false)
Start-Sleep -Seconds 18

# استخراج الرابط وحفظه
if (Test-Path $tunnelLog) {
    $content = Get-Content $tunnelLog -Raw
    if ($content -match 'https://[a-zA-Z0-9-]+\.trycloudflare\.com') {
        $matches[0] | Set-Content (Join-Path $dir "tunnel_url.txt")
    }
}
