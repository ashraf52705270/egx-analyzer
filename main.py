import sys, os, json, logging, argparse, threading, webbrowser, subprocess, time
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

# تحميل ملف .env إن وجد
load_dotenv()

# Configuration - إعدادات التطبيق
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.getenv("EGX_HOST", "0.0.0.0")
PORT = int(os.getenv("EGX_PORT", "8000"))
DEBUG = os.getenv("EGX_DEBUG", "false").lower() == "true"

SECRET_KEY = os.getenv("EGX_SECRET_KEY", "egx-v2-change-this-secret-key-in-production-64bytes!!")
JWT_EXPIRY_HOURS = int(os.getenv("EGX_JWT_EXPIRY", "24"))
CORS_ORIGINS_RAW = os.getenv("EGX_CORS_ORIGINS", "http://localhost:8000,http://localhost:8780")
CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]

DB_PATH = os.getenv("EGX_DB_PATH", str(DATA_DIR / "egx_v2.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "")  # PostgreSQL: postgresql://user:pass@host/db

# Rate limiting
RATE_LIMIT_GLOBAL = os.getenv("EGX_RATE_LIMIT", "60/minute")

DATA_TTL = int(os.getenv("EGX_DATA_TTL", "120"))
ENGINE_INTERVAL = int(os.getenv("EGX_ENGINE_INTERVAL", "30"))

DEFAULT_CAPITAL = 10000
DEFAULT_RISK_PCT = 2.0
DEFAULT_MAX_OPEN = 5
DEFAULT_MIN_QUALITY = 65
DEFAULT_MIN_RR = 1.5
DEFAULT_MIN_LIQUIDITY = 30
DEFAULT_MIN_CONFIRMATION = 2
DEFAULT_MIN_ADX = 15
DEFAULT_MIN_REL_VOL = 0.5
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_MAX_RISK_PCT_PER_TRADE = 8.0
DEFAULT_DAILY_LOSS_LIMIT = 5.0

MARKET_OPEN_HOUR = 10
MARKET_OPEN_MINUTE = 0
MARKET_CLOSE_HOUR = 14
MARKET_CLOSE_MINUTE = 30
CAIRO_TZ_OFFSET = 2

RISK_DISCLAIMER = """
⚠️ تنويه مخاطر مهم
هذا التطبيق للأغراض التعليمية والبحثية فقط ولا يعتبر استشارة مالية.
قرارات التداول الآلية تحمل مخاطر مالية كبيرة وقد تؤدي إلى خسارة رأس المال.
المستخدم يتحمل المسؤولية الكاملة عن قراراته الاستثمارية.
لا تداول بأموال لا تتحمل خسارتها.
"""

TRADE_MODE_AUTO = "auto"
from database import *
from analysis import *
from engine import *
from api import router, get_data_manager, set_engine, get_engine

_engine: Optional[DecisionEngine] = None

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """تهيئة التطبيق عند البدء والإغلاق"""
    global _engine
    _logger = logging.getLogger(__name__)
    _logger.info("=" * 55)
    _logger.info("  EGX Statistical Analyzer v2")
    _logger.info("  محلل البورصة المصرية الإحصائي")
    _logger.info("=" * 55)
    init_db()
    _logger.info("قاعدة البيانات جاهزة")
    _logger.info(RISK_DISCLAIMER)

    try:
        dm = get_data_manager()
        settings = load_settings()
        defaults_written = False
        for key, val in [("min_adx", DEFAULT_MIN_ADX), ("min_rel_vol", DEFAULT_MIN_REL_VOL),
                          ("max_risk_pct", DEFAULT_MAX_RISK_PCT_PER_TRADE),
                          ("max_consecutive_losses", DEFAULT_MAX_CONSECUTIVE_LOSSES)]:
            if key not in settings:
                settings[key] = val
                defaults_written = True
        if defaults_written:
            save_settings(settings)
        mode = settings.get("trade_mode", TRADE_MODE_AUTO)
        daily_limit = settings.get("daily_loss_limit", DEFAULT_DAILY_LOSS_LIMIT)

        _engine = DecisionEngine(
            data_manager=dm,
            mode=mode,
            daily_loss_limit=daily_limit,
        )
        _engine.start()
        set_engine(_engine)
        _logger.info(f"تم بدء محرك القرار تلقائياً (الوضع: {mode})")
    except Exception as e:
        _logger.warning(f"لم يتم بدء محرك القرار تلقائياً: {e}")

    yield

    logging.getLogger(__name__).info("جاري إغلاق التطبيق...")

app = FastAPI(
    title="EGX Statistical Analyzer v2",
    description="محلل البورصة المصرية الإحصائي",
    version="2.0.0",
    lifespan=_lifespan,
)

static_dir = SCRIPT_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rate limiter — حد أقصى للطلبات (يمنع إساءة الاستخدام)
limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_GLOBAL])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(router)

# ── متابعة الزوار ──
@app.middleware("http")
async def track_visits(request: Request, call_next):
    """تسجيل زيارات الموقع (يتخطى ملفات static و API الداخلية)"""
    import time
    from database import log_visit
    path = request.url.path
    # استخراج IP حقيقي خلف proxy (X-Forwarded-For, X-Real-IP)
    forwarded = request.headers.get("x-forwarded-for", "")
    real_ip = request.headers.get("x-real-ip", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif real_ip:
        ip = real_ip.strip()
    else:
        ip = request.client.host if request.client else "unknown"
    # نسجل بس الصفحات الرئيسية + ping (عشان SPA)
    if path in ("/", "/index.html", "/api/ping"):
        ua = request.headers.get("user-agent", "")
        try:
            log_visit(ip, ua, path)
        except Exception:
            pass
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    response.headers["X-Process-Time"] = str(round(elapsed, 3))
    return response


# ══════════════════════════════════════════════════════════════════════════════
# نقطة الدخول الرئيسية - Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="EGX Statistical Analyzer v2 - محلل البورصة المصرية",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
أمثلة:
  python egx_analyzer.py                تشغيل على localhost:8000
  python egx_analyzer.py --port 9000    تشغيل على بورت 9000
  python egx_analyzer.py --host 0.0.0.0 --port 8000    تشغيل متاح من الشبكة
  python egx_analyzer.py --debug        وضع التطوير مع إعادة التحميل التلقائي
        """,
    )
    parser.add_argument("--host", default=None, help="عنوان السيرفر (افتراضي: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="رقم البورت (افتراضي: 8000)")
    parser.add_argument("--debug", action="store_true", help="وضع التطوير (إعادة تحميل تلقائية)")
    args = parser.parse_args()

    host = args.host or HOST
    port = args.port or PORT
    debug = args.debug or DEBUG

    print("=" * 55)
    print("  EGX Statistical Analyzer v2")
    print("  محلل البورصة المصرية الإحصائي")
    print("=" * 55)
    print(f"  العنوان: http://localhost:{port}")
    print(f"  وضع التطوير: {'نعم' if debug else 'لا'}")
    print(f"  قاعدة البيانات: {DB_PATH}")
    print("=" * 55)
    print()
    print("⚡ اضغط Ctrl+C لإيقاف السيرفر")
    print()
    print("⚠️ تنويه: هذا التطبيق للأغراض التعليمية فقط ولا يعتبر استشارة مالية")
    print()

    # فتح المتصفح تلقائياً بعد تأخير بسيط (يفضل App Mode كشاشة مستقلة)
    browser_url = f"http://localhost:{port}"

    def _open_browser_app_mode():
        time.sleep(1.5)
        try:
            # محاولة فتح كتطبيق مستقل (App Mode) - شاشة بدون شريط عناوين
            app_mode_opened = False
            if sys.platform == "win32":
                chrome_paths = [
                    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"),
                    os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
                ]
                for cpath in chrome_paths:
                    if os.path.exists(cpath):
                        try:
                            subprocess.Popen([cpath, f"--app={browser_url}", "--window-size=1400,900"])
                            app_mode_opened = True
                            break
                        except Exception:
                            continue
            if not app_mode_opened:
                webbrowser.open(browser_url)
        except Exception:
            try:
                webbrowser.open(browser_url)
            except Exception:
                pass

    threading.Thread(target=_open_browser_app_mode, daemon=True).start()

    # Use import string that works when file is run directly
    uvicorn.run(
        f"{os.path.splitext(os.path.basename(__file__))[0]}:app",
        host=host,
        port=port,
        reload=debug,
    )