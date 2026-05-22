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

## آخر التعديلات (20 مايو 2026)

### تصحيح `detect_market_distribution()` في `engine.py:1153`
- الدالة بتستقبل `stocks: Dict[str, StockData]` مش `Dict[str, dict]`
- حصل `AttributeError: 'StockData' object has no attribute 'get'` لأنها كانت بتستخدم `v.get("price", 0)`
- التصحيح: استخدام `isinstance(v, dict)` للتفريق، وتحويل `StockData` → dict via `vars(v)`:
  ```python
  vd = v if isinstance(v, dict) else vars(v)
  ```
- دا سبب إن البانر/البادجات ما كانتش تظهر — المحرك كان بيكراش في أول دورة

### إضافة كشف صرف/تجميع سوقي
- دالة `detect_market_distribution()` في `engine.py`:
  - تحسب `advancing_pct`, `below_open_pct`, `volume_surge_red/green`, `near_low/high_pct`
  - ترجع `state` (صرف/تجميع/عادي), `severity` (0–5), `warnings`
- `_execute_cycle()` في `engine.py:308` تستدعيها كل دورة
- لو `severity >= 4` للصرف → `block_new = True` (يمنع فتح صفقات جديدة)
- لو `severity >= 3` للتجميع → تخفيف عتبات الدخول (min_quality=50, min_rr=1.2, min_liq=25, min_confirm=2, min_adx=12, min_rel_vol=0.3)

### واجهة المستخدم — بانر وبادجات
- `index.html`:
  - `marketDistBanner` (line 1594): بانر أحمر/أخضر/أصفر فوق بطاقات أفضل الفرص
  - `_marketDistribution` (line 2099): قراءة من `/api/top`
  - `renderOppCards()` (line 3008-3016): بادج لكل سهم:
    - `md.distribution && severity >= 4` → 🚫 صرف جماعي
    - `md.accumulation && severity >= 3` → ✅ تجميع سوقي
    - غير كده → ✅/🎯/⏳ العادية

### API
- `/api/top` يرجع `market_distribution` كحقل رئيسي + كل سهم فيه `market_distribution` في الكارد
- `/api/settings` يدعم `test_mode: bool` — بيدخل في SettingsUpdate (line 126)
- `/api/engine/status` يرجع `running`, `mode`, `daily_pnl`, إلخ

### ترشيح الإشارات
- `renderAutoSignals()` (index.html): بتعرض بس OPEN signals
- `renderTrades()`: بتعرض بس open/active trades (الـ closed مختفية)
- `Trade.to_dict()` في `database.py`: فيها `auto: self.signal_log_id is not None`

### حفظ التواريخ
- `_dict_to_trade()` في `database.py`: بتحافظ على `entry_date`/`exit_date` من JSON (parsing `fromisoformat`)
- `to_dict()` في `database.py`: كانت ناقصة `auto` — اتضافت
- `_open_trade()` في `engine.py`: الـ `notes` دلوقتي dict مش string

### تشغيل السيرفر على Windows
- `python main.py` من مجلد EGX Analyzer
- أو double-click `EGX Analyzer.lnk` على سطح المكتب
- بعد إعادة التشغيل، لو عايز المحرك يشتغل بره ساعات التداول: شغّل `test_mode` من الإعدادات أو POST `/api/settings` بـ `{"test_mode": true}`
- أحياناً PowerShell بيلخبط في التشفير: استخدم `$env:PYTHONIOENCODING='utf-8'` قبل أي أمر Python inline
- `detect_market_distribution()` ممكن تبوظ لو `StockData` متحولش dict — التصحيح فوق

## PIN للمساعدة
- المستخدم بيتكلم عربى
- يفضل اختصار فى الردود
- الملفات على سطح المكتب: EGX Analyzer مجلد، المؤشر مجلد
