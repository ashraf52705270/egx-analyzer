# EGX Statistical Analyzer v2 — محلل البورصة المصرية

تحليل فني آلي للبورصة المصرية باستخدام TradingView API. يكتشف فرص التداول، يشغّل استراتيجيات آلية، ويسجل النتائج في قاعدة بيانات.

## المميزات
- جلب وتحليل 285 سهم مصري في الوقت الفعلي
- 15+ فلتر فني (ADX, RSI, SMA, حجم نسبي، وقف خسارة ذكي، إلخ)
- محرك قرارات آلي (Autopilot) مع تسجيل الرفض
- باك تيست مع إحصائيات الأداء
- نظام حسابات (تسجيل/دخول) مع JWT
- دعم كامل للغة العربية

## التشغيل السريع

### محلياً
```bash
pip install -r requirements.txt
python main.py
# افتح http://localhost:8000
```

### بـ Docker
```bash
docker compose up --build
```

### متغيرات البيئة (اختياري — `.env`)
```bash
EGX_SECRET_KEY=غير-هذا-المفتاح
EGX_CORS_ORIGINS=https://example.com
EGX_PORT=8000
```

## هيكل المشروع
```
├── main.py          # نقطة الدخول + FastAPI app
├── api.py           # جميع endpoints API
├── database.py      # SQLAlchemy models + CRUD
├── analysis.py      # تحليل البيانات وإدارة المصادر
├── engine.py        # محرك القرار الآلي
├── index.html       # الواجهة الأمامية
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## المميزات الإضافية
- **Rate Limiting** — حد أقصى 60 طلب/دقيقة (يمنع إساءة الاستخدام)
- **PostgreSQL** — دعم MySQL/PostgreSQL عبر متغير `DATABASE_URL`
- **إشعارات تليجرام** — يتم إرسال الإشارات تلقائياً إلى بوت تليجرام عند التفعيل
  (ضبط `EGX_TELEGRAM_BOT_TOKEN` و `EGX_TELEGRAM_CHAT_ID` في `.env`)
- **دعم HTTPS** — ملف nginx.conf جاهز مع Let's Encrypt
- **واجهة Responsive** — تدعم الموبايل والتابلت
- **نشر آلي** — deploy/install.sh ينصب التطبيق على سيرفر Ubuntu

## API
التوثيق التلقائي متاح في `/docs` بعد تشغيل السيرفر.

## تنويه
للأغراض التعليمية فقط. التداول ينطوي على مخاطر مالية كبيرة.
