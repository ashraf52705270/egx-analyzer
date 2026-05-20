# EGX Analyzer

محلل البورصة المصرية (EGX) — تطبيق ويب لتحليل الأسهم المصرية فنى، إشارات بيع/شراء، ومحرك قرار آلى.

## التقنية
- **Backend:** Python + FastAPI (uvicorn)
- **Frontend:** HTML/CSS/JS (ملف واحد: index.html)
- **قاعدة بيانات:** SQLite (data/egx_v2.db)
- **Docker:** موجود (Dockerfile + docker-compose.yml)
- **نشر:**
  - Replit: https://egx-analyzer--ashraf5270.replit.app
  - GitHub: https://github.com/ashraf52705270/egx-analyzer

## تشغيل محلى
- `main.py` — ملف التشغيل الرئيسى
- ايستخدم `python main.py` — السيرفر على http://localhost:8000
- shortcut على سطح المكتب: **EGX Analyzer.lnk** (بيشغل start_local.vBS)

## الملفات الأساسية
- `main.py` — نقطة الدخول و FastAPI app
- `analysis.py` — كل التحليل الفنى (RSI, MACD, ADX, Fibonacci, Divergence, Patterns...)
- `api.py` — API endpoints (auth, settings, trades, signals)
- `engine.py` — محرك القرار الآلى
- `database.py` — قاعدة البيانات
- `index.html` — الواجهة الأمامية الكاملة (6173 سطر)
- `notify.py` — نظام الإشعارات (Telegram)
- `check_signals.py` — أداة فحص الإشارات

## مؤشر TradingView
- `C:\Users\ashra\OneDrive\Desktop\المؤشر\egx_analyzer_full.pine`
- Pine Script v5 بكل الشروط من التحليل الأصلى
- فيه Score, إشارات, أنماط شموع, Divergence, Fibonacci, Pivot Points, لوحة معلومات

## التعديلات الأخيرة
- تعديل نظام الدخول: guest auto-login يعطى role=user (مايظهرش admin tab)
- إضافة guest API endpoint
- التنظيف: إزالة ملفات مؤقتة (cloudflared, railway, caches, logs)
- تغيير اسم المجلد من "New folder" لـ "EGX Analyzer"
- إنشاء start_local.vBS لتشغيل السيرفر بدون نافذة cmd

## عشان تدخل كـ admin
- افتح اللينك → تسجيل دخول → اكتب email (admin@example.com) وأى باسورد

## نشر على Replit
- Import من GitHub: https://github.com/ashraf52705270/egx-analyzer

## PIN للمساعدة
- المستخدم بيتكلم عربى
- يفضل اختصار فى الردود
- الملفات على سطح المكتب: EGX Analyzer مجلد، المؤشر مجلد
