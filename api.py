import sys, os, json, logging, time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query, Request as FastAPIRequest
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

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
CORS_ORIGINS = os.getenv("EGX_CORS_ORIGINS", "http://localhost:8000,http://localhost:8780").split(",")

DB_PATH = os.getenv("EGX_DB_PATH", str(DATA_DIR / "egx_v2.db"))

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
from engine import DecisionEngine, _get_html_frontend

# ═══════════════════════════════════════════════════════════════
# مدير البيانات العام (Singleton)
# Global Data Manager
# ═══════════════════════════════════════════════════════════════

router = APIRouter()

_data_manager: Optional[DataManager] = None
_engine: Optional[DecisionEngine] = None
_last_fetch_time: float = 0.0


def get_data_manager() -> DataManager:
    """الحصول على مدير البيانات — إنشاء واحد فقط"""
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager(ttl=DATA_TTL)
    return _data_manager


def get_engine() -> Optional[DecisionEngine]:
    """الحصول على محرك القرار"""
    return _engine


def set_engine(engine: Optional[DecisionEngine]) -> None:
    """تعيين محرك القرار"""
    global _engine
    _engine = engine


# ═══════════════════════════════════════════════════════════════
# نماذج Pydantic للطلبات والاستجابات
# Pydantic Models for Request/Response
# ═══════════════════════════════════════════════════════════════


class LoginRequest(BaseModel):
    """طلب تسجيل الدخول"""
    email: str = Field("admin@example.com", description="البريد الإلكتروني")
    password: str = Field("", description="كلمة المرور")


class SetupRequest(BaseModel):
    """طلب إعداد كلمة المرور لأول مرة"""
    email: str = Field("admin@example.com", description="البريد الإلكتروني")
    password: str = Field(..., min_length=6, description="كلمة المرور الجديدة (6 أحرف على الأقل)")


class SettingsUpdate(BaseModel):
    """تحديث الإعدادات"""
    capital: Optional[float] = None
    risk_pct: Optional[float] = None
    max_open_trades: Optional[int] = None
    min_quality: Optional[float] = None
    min_rr: Optional[float] = None
    min_liq: Optional[float] = None
    min_confirm: Optional[int] = None
    min_adx: Optional[float] = None
    min_rel_vol: Optional[float] = None
    max_risk_pct: Optional[float] = None
    max_consecutive_losses: Optional[int] = None
    auto_open: Optional[bool] = None
    auto_close: Optional[bool] = None
    test_mode: Optional[bool] = None
    trade_mode: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    ad_image_url: Optional[str] = None
    ad_link_url: Optional[str] = None
    ad_top_image: Optional[str] = None
    ad_top_link: Optional[str] = None
    ad_top_enabled: Optional[bool] = None
    ad_bottom_image: Optional[str] = None
    ad_bottom_link: Optional[str] = None
    ad_bottom_enabled: Optional[bool] = None
    ad_whatsapp: Optional[str] = None
    ad_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None


class TradeCreate(BaseModel):
    """إنشاء صفقة جديدة"""
    symbol: str = Field(..., min_length=1, description="رمز السهم")
    entry_price: float = Field(..., gt=0, description="سعر الدخول")
    shares: int = Field(0, ge=0, description="عدد الأسهم")
    stop_loss: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    target3: Optional[float] = None
    near_t1: Optional[float] = None
    near_t2: Optional[float] = None
    near_t3: Optional[float] = None
    trade_quality: Optional[float] = None
    signal_type: Optional[str] = None
    notes: Optional[str] = None


class TradeClose(BaseModel):
    """إغلاق صفقة"""
    id: int = Field(..., description="معرف الصفقة")
    exit_price: float = Field(..., gt=0, description="سعر الخروج")


class TradeDelete(BaseModel):
    """حذف صفقة"""
    id: int = Field(..., description="معرف الصفقة")


class EngineModeUpdate(BaseModel):
    """تحديث وضع المحرك"""
    mode: str = Field("auto", description="وضع التداول: auto / semi_auto / manual")


# ═══════════════════════════════════════════════════════════════
# التبعيات (Dependencies)
# Dependencies
# ═══════════════════════════════════════════════════════════════


async def get_current_user(request: FastAPIRequest) -> Dict[str, Any]:
    """
    التحقق من رمز JWT — يُستخدم كتبعية للنقاط المحمية
    في وضع المستخدم الواحد (بدون كلمة مرور)، يُسمح بالوصول مباشرة
    Verify JWT token — used as dependency for protected endpoints
    In single-user mode (no password set), access is allowed directly
    """
    # التحقق مما إذا تم تعيين كلمة مرور
    settings = load_settings()
    password_hash = settings.get("password_hash")

    # وضع المستخدم الواحد: لا توجد كلمة مرور → وصول مباشر
    if not password_hash:
        return {"sub": "admin", "role": "admin", "mode": "single_user", "plan": "premium"}

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="رمز المصادقة مفقود أو غير صالح",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]  # إزالة "Bearer "
    payload = verify_jwt_token(token)

    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="رمز المصادقة منتهي الصلاحية أو غير صالح",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # جلب خطة المستخدم من قاعدة البيانات
    username = payload.get("sub", "")
    plan = _get_user_plan(username)
    payload["plan"] = plan

    return payload


def _get_user_plan(user_id: str) -> str:
    """جلب خطة المستخدم (premium/free) من قاعدة البيانات"""
    if not user_id:
        return "free"
    user = None
    if '@' in user_id:
        from database import get_user_by_email
        user = get_user_by_email(user_id)
    if not user:
        from database import get_user_by_username
        user = get_user_by_username(user_id)
    if not user:
        # مستخدم غير موجود في DB (مثل الأدمن من الإعدادات) → premium
        return "premium"
    plan = user.get("plan", "free")
    if plan == "premium":
        premium_until = user.get("premium_until")
        if premium_until:
            try:
                if isinstance(premium_until, str):
                    from datetime import datetime
                    expiry = datetime.fromisoformat(premium_until)
                else:
                    expiry = premium_until
                if expiry < datetime.utcnow():
                    return "free"  # انتهت صلاحية البريميوم
            except Exception:
                pass
        return "premium"
    return "free"


async def require_premium(user: Dict = Depends(get_current_user)) -> Dict:
    """فترة تجريبية — كل الميزات مفتوحة للجميع"""
    return user


def _is_password_set() -> bool:
    """التحقق مما إذا تم تعيين كلمة المرور"""
    settings = load_settings()
    return bool(settings.get("password_hash"))


# ═══════════════════════════════════════════════════════════════
# دوال مساعدة داخلية
# Internal Helper Functions
# ═══════════════════════════════════════════════════════════════


def _get_stocks_with_analysis() -> Dict[str, Any]:
    """جلب بيانات الأسهم مع التحليل الفني"""
    dm = get_data_manager()
    stocks = dm.get_stocks()

    if not stocks:
        return {}

    result = {}
    for sym, stock_data in stocks.items():
        v = stock_data.to_dict() if hasattr(stock_data, "to_dict") else stock_data
        if v.get("analysis") is None and v.get("price"):
            v["analysis"] = analyze_stock(sym, v)
        result[sym] = v

    global _last_fetch_time
    _last_fetch_time = time.time()

    return result


def _analyze_performance() -> Dict[str, Any]:
    """تحليل الصفقات المغلقة لتقييم جودة الإشارات"""
    trades = load_trades()
    closed = [tr for tr in trades if tr.get("status") == "closed" and tr.get("pnl_pct") is not None]

    if not closed:
        return {"ok": False, "msg": "لا توجد صفقات مغلقة بعد"}

    wins = [tr for tr in closed if (tr.get("pnl_pct") or 0) > 0]
    losses = [tr for tr in closed if (tr.get("pnl_pct") or 0) <= 0]
    total = len(closed)
    win_rate = round(len(wins) / total * 100, 1)

    avg_win = round(sum(tr["pnl_pct"] for tr in wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(tr["pnl_pct"] for tr in losses) / len(losses), 2) if losses else 0
    total_pnl = round(sum(tr.get("pnl", 0) or 0 for tr in closed), 2)

    # تحليل حسب نوع الإشارة
    by_signal: Dict[str, Any] = {}
    for tr in closed:
        st = tr.get("signal_type", "UNKNOWN")
        if st not in by_signal:
            by_signal[st] = {"count": 0, "wins": 0, "total_pnl": 0}
        by_signal[st]["count"] += 1
        by_signal[st]["total_pnl"] += tr.get("pnl", 0) or 0
        if (tr.get("pnl_pct") or 0) > 0:
            by_signal[st]["wins"] += 1

    for st in by_signal:
        c = by_signal[st]["count"]
        by_signal[st]["win_rate"] = round(by_signal[st]["wins"] / c * 100, 1) if c > 0 else 0

    # تحليل حسب جودة الصفقة
    quality_buckets: Dict[str, List[float]] = {"≥80": [], "60-79": [], "<60": []}
    for tr in closed:
        tq = tr.get("trade_quality") or 0
        bucket = "≥80" if tq >= 80 else "60-79" if tq >= 60 else "<60"
        quality_buckets[bucket].append(tr.get("pnl_pct", 0) or 0)

    quality_analysis: Dict[str, Any] = {}
    for bucket, pnls in quality_buckets.items():
        if pnls:
            wins_b = len([p for p in pnls if p > 0])
            quality_analysis[bucket] = {
                "count": len(pnls),
                "win_rate": round(wins_b / len(pnls) * 100, 1),
                "avg_pnl": round(sum(pnls) / len(pnls), 2),
            }

    # توصيات بناءً على البيانات
    recommendations: List[str] = []
    if win_rate < 40:
        recommendations.append("⚠️ نسبة الفوز أقل من 40% — ارفع الحد الأدنى للجودة إلى 80")
    if avg_win < abs(avg_loss) * 1.5:
        recommendations.append("⚠️ متوسط الربح أقل من 1.5× متوسط الخسارة — استخدم فلتر R:R أصغر")
    if quality_analysis.get("<60", {}).get("win_rate", 100) < 40:
        recommendations.append("✅ الصفقات بجودة < 60 خاسرة — فعّل فلتر الجودة ≥ 60")
    if win_rate >= 60 and avg_win >= abs(avg_loss) * 2:
        recommendations.append("🎯 النظام يعمل بشكل جيد — حافظ على الإعدادات الحالية")

    return {
        "ok": True,
        "total_trades": total,
        "win_rate": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "total_pnl_egp": total_pnl,
        "expectancy": round(win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss, 2),
        "by_signal": by_signal,
        "quality_analysis": quality_analysis,
        "recommendations": recommendations,
    }


# ═══════════════════════════════════════════════════════════════
# 1. GET / — تقديم واجهة المستخدم
# Serve HTML Frontend
# ═══════════════════════════════════════════════════════════════


@router.get("/")
async def serve_frontend():
    """تقديم واجهة المستخدم HTML (من ملف index.html مع fallback)"""
    html = _get_html_frontend()
    return HTMLResponse(content=html, status_code=200)


# ═══════════════════════════════════════════════════════════════
# 2. GET /api/all — جميع بيانات الأسهم مع التحليل
# All stock data with analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/all")
async def get_all_stocks(offset: int = 0, limit: int = 0):
    """جلب بيانات الأسهم مع التحليل الفني (مع Pagination)"""
    dm = get_data_manager()
    age = round(time.time() - _last_fetch_time) if _last_fetch_time else 0
    data = _get_stocks_with_analysis()

    if data:
        items = list(data.items())
        total = len(items)
        if limit > 0:
            items = items[offset:offset + limit]
        sliced = dict(items)
        return {"ok": True, "loading": False, "count": total, "returned": len(sliced), "age_sec": age, "data": sliced}
    return {"ok": True, "loading": True, "count": 0, "age_sec": 0, "data": {}}


# ═══════════════════════════════════════════════════════════════
# 3. GET /api/ready — فحص جاهزية النظام
# System readiness check
# ═══════════════════════════════════════════════════════════════


@router.get("/api/ready")
async def check_ready():
    """فحص جاهزية النظام"""
    dm = get_data_manager()
    age = round(time.time() - _last_fetch_time) if _last_fetch_time else 0
    mstatus, mcode = market_status()
    egx30_price, egx30_chg = None, None
    try:
        egx30_price, egx30_chg = dm._source.fetch_index("EGX30")
    except Exception:
        pass

    stocks = dm.get_stocks()
    return {
        "ok": True,
        "ready": bool(stocks),
        "count": len(stocks),
        "age_sec": age,
        "market_status": mstatus,
        "market_code": mcode,
        "is_open": is_trading_hours(),
        "egx30_price": egx30_price,
        "egx30_chg": egx30_chg,
    }


# ═══════════════════════════════════════════════════════════════
# 4. GET /api/status — حالة النظام
# System status
# ═══════════════════════════════════════════════════════════════


@router.get("/api/status")
async def get_status():
    """حالة النظام الحالية"""
    dm = get_data_manager()
    age = round(time.time() - _last_fetch_time) if _last_fetch_time else 0
    mstatus, mcode = market_status()
    stocks = dm.get_stocks()
    return {
        "ok": True,
        "count": len(stocks),
        "age_sec": age,
        "next": max(0, DATA_TTL - age),
        "ready": bool(stocks),
        "market_status": mstatus,
        "market_code": mcode,
        "is_open": is_trading_hours(),
    }


# ═══════════════════════════════════════════════════════════════
# 5. GET /api/refresh — إجبار تحديث البيانات
# Force data refresh
# ═══════════════════════════════════════════════════════════════


@router.get("/api/refresh")
async def refresh_data():
    """إجبار تحديث بيانات الأسهم"""
    dm = get_data_manager()
    dm.reset_cache()
    stocks = dm.get_stocks(force_refresh=True)
    global _last_fetch_time
    _last_fetch_time = time.time()
    return {"ok": True, "count": len(stocks)}


# ═══════════════════════════════════════════════════════════════
# 6. GET /api/stock?t=SYMBOL — تحليل سهم واحد
# Single stock analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/stock")
async def get_stock(t: str = Query(..., description="رمز السهم")):
    """تحليل سهم واحد"""
    symbol = t.upper()
    dm = get_data_manager()
    stocks = dm.get_stocks()

    if symbol in stocks:
        stock_data = stocks[symbol]
        v = stock_data.to_dict() if hasattr(stock_data, "to_dict") else stock_data
        v["analysis"] = analyze_stock(symbol, v)
        return {"ok": True, "symbol": symbol, **v}
    return {"ok": False, "error": "not found"}


# ═══════════════════════════════════════════════════════════════
# 7. GET /api/signals?type=BUY — إشارات مُصفاة
# Filtered signals
# ═══════════════════════════════════════════════════════════════


@router.get("/api/signals")
async def get_signals(type: str = Query("", description="نوع الإشارة: BUY, SELL, ALL")):
    """جلب الإشارات المُصفاة حسب النوع"""
    sig_type = type.upper()
    data = _get_stocks_with_analysis()
    filtered: Dict[str, Any] = {}

    for sym, v in data.items():
        a = v.get("analysis", {})
        if not a:
            continue
        st = a.get("signal_type", "")
        if not sig_type or st == sig_type or sig_type == "ALL":
            t = a.get("trade", {})
            filtered[sym] = {
                "price": v.get("price"),
                "change_pct": v.get("change_pct"),
                "signal": a.get("signal"),
                "signal_color": a.get("signal_color"),
                "signal_type": st,
                "score": a.get("score"),
                "sector": v.get("sector"),
                "rsi": v.get("rsi"),
                "adx": v.get("adx"),
                "adx_label": a.get("adx_label"),
                "volume": v.get("volume"),
                "vol_class": a.get("vol_class"),
                "entry": t.get("entry_ideal"),
                "stop": t.get("stop_loss"),
                "target1": t.get("targets", [None])[0],
                "vs_egx30": a.get("vs_egx30"),
            }

    return {"ok": True, "count": len(filtered), "signals": filtered}


# ═══════════════════════════════════════════════════════════════
# 8. GET /api/top — أفضل الفرص
# Top trading opportunities
# ═══════════════════════════════════════════════════════════════


@router.get("/api/top")
async def get_top_opportunities(user: Dict = Depends(require_premium)):
    """جلب أفضل الفرص التجارية"""
    data = _get_stocks_with_analysis()
    scored: List[Dict[str, Any]] = []

    # تحميل الإعدادات مرة واحدة (مش في كل تكرار)
    settings_top = load_settings()
    min_q  = settings_top.get("min_quality", 70)
    min_r  = settings_top.get("min_rr", 1.5)
    min_l  = settings_top.get("min_liq", 40)
    min_c  = settings_top.get("min_confirm", 3)
    min_adx_top  = settings_top.get("min_adx", DEFAULT_MIN_ADX)
    min_rv_top   = settings_top.get("min_rel_vol", DEFAULT_MIN_REL_VOL)

    for sym, v in data.items():
        a = v.get("analysis", {})
        if not a:
            continue
        st = a.get("signal_type", "")
        if st not in ("BUY_STRONG", "BUY", "ACCUMULATE"):
            continue
        t = a.get("trade", {})
        rr1 = t.get("rr1", 0) or 0
        liq = t.get("liq_score", 0) or 0
        tq = t.get("trade_quality", 0) or 0
        prox = t.get("proximity", 0) or 0
        ready = t.get("ready", False)
        scenario = t.get("entry_scenario", "WAIT")
        # ترتيب الأولوية: MARKET (ادخل الآن) +40، NEAR +20، WAIT +0
        scenario_bonus = 40 if scenario == "MARKET" else 20 if scenario == "NEAR" else 0
        bull_c = (a.get("confirmation") or {}).get("bull_count", 0)
        adx_v  = v.get("adx") or 0
        rel_v  = (v.get("volume", 0) / v.get("avg_vol", 1)) if v.get("avg_vol", 0) > 0 else 0
        prc_v  = v.get("price") or 0
        sma_v  = v.get("sma50") or 0
        price_above_sma50_top = prc_v > sma_v if (prc_v and sma_v) else True
        if rr1 < 1.5 or liq < 20:
            continue

        # السهم اللي يستوفي كل شروط الطيار الآلي يأخذ +50 نقطة إضافية
        engine_ready = (
            tq >= min_q and
            rr1 >= min_r and
            liq >= min_l and
            bull_c >= min_c and
            scenario in ("MARKET", "NEAR") and
            adx_v >= min_adx_top and
            rel_v >= min_rv_top and
            price_above_sma50_top
        )
        engine_bonus = 50 if engine_ready else 0

        sort_score = tq + scenario_bonus + (10 if ready else 0) + engine_bonus
        scored.append({
            "symbol": sym,
            "name": v.get("tv_name", sym),
            "price": v.get("price"),
            "change_pct": v.get("change_pct"),
            "signal": a.get("signal"),
            "signal_color": a.get("signal_color"),
            "signal_type": st,
            "score": a.get("score"),
            "trade_quality": round(tq, 1),
            "quality_label": t.get("quality_label", ""),
            "sort_score": round(sort_score, 1),
            "engine_ready": engine_ready,  # يستوفي شروط الطيار الآلي
            "ready": ready,
            "proximity": round(prox, 1),
            "rsi": v.get("rsi"),
            "adx": v.get("adx"),
            "adx_label": a.get("adx_label", ""),
            "sector": v.get("sector"),
            "vol_class": a.get("vol_class", ""),
            "liq_score": liq,
            "liq_label": t.get("liq_label", ""),
            "slip_pct": t.get("slip_pct", 0),
            "entry": t.get("entry_ideal"),
            "entry_high": t.get("entry_range_high"),
            "entry_low": t.get("entry_range_low"),
            "entry_scenario": t.get("entry_scenario", "WAIT"),
            "stop": t.get("stop_loss"),
            "targets": t.get("targets", []),
            "far_pcts": t.get("far_pcts", []),
            "near_targets": t.get("near_targets", []),
            "near_pcts": t.get("near_pcts", []),
            "rr": t.get("rr_ratios", []),
            "rr1": rr1,
            "risk_pct": t.get("risk_pct"),
            "market_cap": v.get("market_cap"),
            "volume": v.get("volume"),
            "avg_vol": v.get("avg_vol"),
            "vs_egx30": a.get("vs_egx30"),
            "candle": a.get("candle"),
            "confluence": a.get("multi_fib", {}).get("confluence", []),
            "divergences": a.get("divergences"),
            "confirmation": a.get("confirmation"),
            "trailing_stops": a.get("trailing_stops", []),
            "resistance_info": a.get("resistance_info"),
            "position_data": a.get("position_data"),
            "entry_time_hint": a.get("entry_time_hint"),
        })

    scored.sort(key=lambda x: x["sort_score"], reverse=True)
    ready_count = sum(1 for s in scored if s["ready"])
    near_count = sum(1 for s in scored if not s["ready"] and s["proximity"] >= 70)
    strong_count = sum(1 for s in scored if s["signal_type"] == "BUY_STRONG")

    return {
        "ok": True,
        "count": len(scored),
        "ready_count": ready_count,
        "near_count": near_count,
        "strong_count": strong_count,
        "top": scored[:60],
    }


# ═══════════════════════════════════════════════════════════════
# 9. GET /api/alerts/check?w=SYM1,SYM2 — فحص التنبيهات
# Price alerts
# ═══════════════════════════════════════════════════════════════


@router.get("/api/alerts/check")
async def check_alerts(w: str = Query("", description="رموز الأسهم مفصولة بفاصلة"), user: Dict = Depends(require_premium)):
    """فحص تنبيهات الأسعار لقائمة المراقبة"""
    if not w:
        return {"ok": True, "alerts": []}

    # التحقق من ساعات التداول
    _sett_a = load_settings()
    if not is_trading_hours() and not _sett_a.get("test_mode", False):
        return {"ok": True, "alerts": [], "reason": "market_closed"}

    watch_syms = [s.strip().upper() for s in w.split(",") if s.strip()]
    data = _get_stocks_with_analysis()
    alerts: List[Dict[str, Any]] = []
    TOL = 0.005

    for sym in watch_syms:
        v = data.get(sym)
        if not v:
            continue
        price = v.get("price") or 0
        a = v.get("analysis") or {}
        t = a.get("trade") or {}
        if not price or not t:
            continue

        entry_h = t.get("entry_range_high") or 0
        entry_l = t.get("entry_range_low") or 0
        stop = t.get("stop_loss") or 0
        near = t.get("near_targets") or []
        far = t.get("targets") or []
        entry_i = t.get("entry_ideal") or 0

        def near_lv(p: float, lv: float) -> bool:
            return lv > 0 and abs(p - lv) / lv <= TOL

        triggered: List[Dict[str, Any]] = []

        # تنبيه نطاق الدخول
        if entry_l and entry_h and entry_l <= price <= entry_h:
            triggered.append({
                "type": "ENTRY", "level": entry_i,
                "label": "✅ وصل نطاق الدخول",
                "color": "#00e676", "sound": "entry", "price": price,
            })
        elif near_lv(price, stop) or (stop > 0 and price <= stop):
            triggered.append({
                "type": "STOP", "level": stop,
                "label": "🛑 وصل وقف الخسارة",
                "color": "#ff1744", "sound": "stop", "price": price,
            })

        # الأهداف القريبة
        for i, nt in enumerate(near):
            if near_lv(price, nt) or (nt > 0 and price >= nt):
                pct_v = t.get("near_pcts", [0, 0, 0])[i] if t.get("near_pcts") else 0
                triggered.append({
                    "type": f"NEAR_T{i+1}", "level": nt,
                    "label": f"🎯 الهدف القريب {i+1} (+{pct_v}%)",
                    "color": "#69f0ae", "sound": "target", "price": price,
                })

        # الأهداف البعيدة
        for i, ft in enumerate(far):
            if near_lv(price, ft) or (ft > 0 and price >= ft):
                pct_v = t.get("far_pcts", [0, 0, 0])[i] if t.get("far_pcts") else 0
                triggered.append({
                    "type": f"FAR_T{i+1}", "level": ft,
                    "label": f"🏆 الهدف البعيد {i+1} (+{pct_v}%)",
                    "color": "#f6e05e", "sound": "target_far", "price": price,
                })

        # تنبيه أنماط الشموع المهمة
        candle = a.get("candle")
        if candle and candle.get("type") in ("BULLISH", "BEARISH"):
            ctype = f"CANDLE_{candle['type']}_{price:.2f}"
            triggered.append({
                "type": ctype,
                "level": price,
                "label": f"🕯 {candle['ar']}",
                "color": "#f6e05e" if candle["type"] == "BULLISH" else "#fc8181",
                "sound": "target" if candle["type"] == "BULLISH" else "stop",
                "price": price,
            })

        if triggered:
            alerts.append({
                "symbol": sym,
                "name": v.get("tv_name", sym),
                "price": price,
                "change": v.get("change_pct"),
                "triggered": triggered,
            })

    return {"ok": True, "alerts": alerts, "checked": len(watch_syms)}


# ═══════════════════════════════════════════════════════════════
# 10. GET /api/settings — جلب الإعدادات
# Get settings
# ═══════════════════════════════════════════════════════════════


@router.get("/api/settings")
async def get_settings():
    """جلب إعدادات التطبيق"""
    settings = load_settings()
    # إزالة الحقول الحساسة مع إضافة مؤشر وجود كلمة مرور
    safe_settings = {k: v for k, v in settings.items() if k not in ("password_hash", "telegram_bot_token")}
    safe_settings["password_hash"] = bool(settings.get("password_hash"))
    tg_token = settings.get("telegram_bot_token", "")
    safe_settings["telegram_bot_token"] = (tg_token[:6] + "****") if tg_token else ""
    safe_settings["telegram_chat_id"] = settings.get("telegram_chat_id", "")
    safe_settings["auth_username"] = settings.get("auth_username", "admin")
    safe_settings["auth_email"] = settings.get("auth_email", "")
    safe_settings["ad_image_url"] = settings.get("ad_image_url", "")
    safe_settings["ad_link_url"] = settings.get("ad_link_url", "")
    safe_settings["ad_top_image"] = settings.get("ad_top_image", "")
    safe_settings["ad_top_link"] = settings.get("ad_top_link", "")
    safe_settings["ad_top_enabled"] = settings.get("ad_top_enabled", False)
    safe_settings["ad_bottom_image"] = settings.get("ad_bottom_image", "")
    safe_settings["ad_bottom_link"] = settings.get("ad_bottom_link", "")
    safe_settings["ad_bottom_enabled"] = settings.get("ad_bottom_enabled", False)
    safe_settings["ad_whatsapp"] = settings.get("ad_whatsapp", "201234567890")
    safe_settings["ad_enabled"] = settings.get("ad_enabled", False)
    safe_settings["smtp_host"] = settings.get("smtp_host", "")
    safe_settings["smtp_port"] = settings.get("smtp_port", 587)
    safe_settings["smtp_user"] = settings.get("smtp_user", "")
    smtp_pass = settings.get("smtp_pass", "")
    safe_settings["smtp_pass"] = (smtp_pass[:4] + "****") if smtp_pass else ""
    safe_settings["smtp_from"] = settings.get("smtp_from", "")
    return {"ok": True, "settings": safe_settings}


# ═══════════════════════════════════════════════════════════════
# 11. POST /api/settings — حفظ الإعدادات
# Save settings
# ═══════════════════════════════════════════════════════════════


@router.post("/api/settings")
async def update_settings(body: SettingsUpdate, user: Dict = Depends(get_current_user)):
    """حفظ إعدادات التطبيق (محمي بكلمة المرور)"""
    current = load_settings()

    # تحديث الإعدادات المرسلة فقط
    update_data = body.model_dump(exclude_none=True)

    # معالجة خاصة لوضع التداول
    if "trade_mode" in update_data:
        mode = update_data["trade_mode"]
        if mode not in (TRADE_MODE_AUTO, TRADE_MODE_SEMI, TRADE_MODE_MANUAL):
            raise HTTPException(status_code=400, detail=f"وضع تداول غير صالح: {mode}")
        # تحديث وضع المحرك إذا كان يعمل
        engine = get_engine()
        if engine and engine.is_running:
            engine.mode = mode

    current.update(update_data)
    save_settings(current)

    # إزالة الحقول الحساسة من الاستجابة
    safe_settings = {k: v for k, v in current.items() if k not in ("password_hash", "telegram_bot_token")}
    safe_settings["password_hash"] = bool(current.get("password_hash"))
    tg_token = current.get("telegram_bot_token", "")
    safe_settings["telegram_bot_token"] = (tg_token[:6] + "****") if tg_token else ""
    safe_settings["telegram_chat_id"] = current.get("telegram_chat_id", "")
    safe_settings["auth_username"] = current.get("auth_username", "admin")
    safe_settings["auth_email"] = current.get("auth_email", "")
    safe_settings["ad_image_url"] = current.get("ad_image_url", "")
    safe_settings["ad_link_url"] = current.get("ad_link_url", "")
    safe_settings["ad_top_image"] = current.get("ad_top_image", "")
    safe_settings["ad_top_link"] = current.get("ad_top_link", "")
    safe_settings["ad_top_enabled"] = current.get("ad_top_enabled", False)
    safe_settings["ad_bottom_image"] = current.get("ad_bottom_image", "")
    safe_settings["ad_bottom_link"] = current.get("ad_bottom_link", "")
    safe_settings["ad_bottom_enabled"] = current.get("ad_bottom_enabled", False)
    safe_settings["ad_whatsapp"] = current.get("ad_whatsapp", "201234567890")
    safe_settings["ad_enabled"] = current.get("ad_enabled", False)
    safe_settings["smtp_host"] = current.get("smtp_host", "")
    safe_settings["smtp_port"] = current.get("smtp_port", 587)
    safe_settings["smtp_user"] = current.get("smtp_user", "")
    smtp_pass = current.get("smtp_pass", "")
    safe_settings["smtp_pass"] = (smtp_pass[:4] + "****") if smtp_pass else ""
    safe_settings["smtp_from"] = current.get("smtp_from", "")
    return {"ok": True, "settings": safe_settings}


# ═══════════════════════════════════════════════════════════════
# 12. GET /api/trades — قائمة التداولات
# List trades
# ═══════════════════════════════════════════════════════════════


@router.get("/api/trades")
async def get_trades():
    """جلب قائمة التداولات مع السعر الحالي للصفقات المفتوحة"""
    trades = load_trades()
    dm = get_data_manager()
    stocks = dm.get_stocks() if dm.cached_stock_count > 0 else {}

    for tr in trades:
        if tr.get("status") == "active":
            sym = tr.get("symbol", "")
            stock_data = stocks.get(sym)
            if stock_data:
                cur = stock_data.price if hasattr(stock_data, "price") else None
            else:
                cur = None
            tr["current_price"] = cur
            if cur and tr.get("entry_price"):
                tr["current_pnl_pct"] = round(
                    (cur - tr["entry_price"]) / tr["entry_price"] * 100, 2
                )
                tr["current_pnl_egp"] = round(
                    (cur - tr["entry_price"]) * tr.get("shares", 0), 2
                )

    return {"ok": True, "trades": trades, "count": len(trades)}


# ═══════════════════════════════════════════════════════════════
# 13. POST /api/trades — إضافة صفقة جديدة
# Add new trade
# ═══════════════════════════════════════════════════════════════


@router.post("/api/trades")
async def create_trade(body: TradeCreate):
    """إضافة صفقة جديدة"""
    trade_data = {
        "symbol": body.symbol.upper(),
        "entry_price": body.entry_price,
        "shares": body.shares,
        "stop_loss": body.stop_loss,
        "targets": [t for t in [body.target1, body.target2, body.target3] if t is not None],
        "near_targets": [t for t in [body.near_t1, body.near_t2, body.near_t3] if t is not None],
        "trade_quality": body.trade_quality,
        "signal_type": body.signal_type,
        "notes": body.notes or "",
        "status": "active",
    }

    try:
        result = add_trade(trade_data)
        return {"ok": True, "trade": result}
    except Exception as e:
        logger.error("خطأ في إضافة الصفقة: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 14. POST /api/trades/close — إغلاق صفقة
# Close a trade
# ═══════════════════════════════════════════════════════════════


@router.post("/api/trades/close")
async def close_trade_endpoint(body: TradeClose):
    """إغلاق صفقة محددة"""
    try:
        result = close_trade(body.id, body.exit_price)
        if result is None:
            raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
        return {"ok": True, "trade": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("خطأ في إغلاق الصفقة %d: %s", body.id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 15. POST /api/trades/delete — حذف صفقة
# Delete a trade
# ═══════════════════════════════════════════════════════════════


@router.post("/api/trades/delete")
async def delete_trade_endpoint(body: TradeDelete):
    """حذف صفقة محددة"""
    try:
        success = delete_trade(body.id)
        if not success:
            raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("خطأ في حذف الصفقة %d: %s", body.id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 16. GET /api/auto/signals — إشارات تلقائية جديدة
# Get new auto signals
# ═══════════════════════════════════════════════════════════════


@router.get("/api/auto/signals")
async def get_auto_signals(user: Dict = Depends(require_premium)):
    """جلب الإشارات التلقائية الجديدة وتفريغ القائمة"""
    engine = get_engine()
    if engine is None:
        return {"ok": True, "signals": [], "count": 0}

    signals = engine.signals
    # تفريغ الإشارات بعد القراءة
    with engine._signals_lock:
        engine._signals.clear()

    return {"ok": True, "signals": signals, "count": len(signals)}


# ═══════════════════════════════════════════════════════════════
# 17. POST /api/test/trigger — اختبار تشغيل إشارة
# Test signal trigger
# ═══════════════════════════════════════════════════════════════


@router.post("/api/test/trigger")
async def test_trigger_signal(user: Dict = Depends(require_premium)):
    """اختبار تشغيل إشارة تجريبية — نفس شروط الطيار الآلي"""
    from analysis import BUY_SIGNALS, ENTRY_SCENARIOS_ALLOWED

    settings = load_settings()
    min_q = settings.get("min_quality", 70)
    min_r = settings.get("min_rr", 1.5)
    min_l = settings.get("min_liq", 40)
    min_c = settings.get("min_confirm", 3)
    min_adx = settings.get("min_adx", 20)
    min_rv = settings.get("min_rel_vol", 1.2)

    data = _get_stocks_with_analysis()
    if not data:
        return {"ok": False, "error": "لا توجد بيانات"}

    engine = get_engine()
    trades = load_trades()
    open_trades = {t["symbol"]: t for t in trades if t.get("status") == "active"}
    triggered: List[str] = []
    count = 0

    for sym, v in data.items():
        if count >= 3:
            break
        a = v.get("analysis", {})
        t = a.get("trade", {})
        st = a.get("signal_type", "")
        tq = t.get("trade_quality", 0) or 0
        rr = t.get("rr1", 0) or 0
        liq = t.get("liq_score", 0) or 0
        conf = a.get("confirmation", {})
        bull_c = conf.get("bull_count", 0)
        scen = t.get("entry_scenario", "WAIT")
        adx_v = v.get("adx") or 0
        rel_v = (v.get("volume", 0) / v.get("avg_vol", 1)) if (v.get("avg_vol") or 0) > 0 else 0
        prc = v.get("price", 0)
        sma = v.get("sma50")
        above_sma = prc > sma if (prc and sma) else True

        conditions = {
            "الطيار الآلي مفعل (auto_open)": settings.get("auto_open", False),
            "السهم غير مفتوح بالفعل": sym not in open_trades,
            "نوع الإشارة (BUY/ACCUMULATE)": st in BUY_SIGNALS,
            f"جودة ≥ {min_q}": tq >= min_q,
            f"RR ≥ {min_r}": rr >= min_r,
            f"سيولة ≥ {min_l}": liq >= min_l,
            f"تأكيد ≥ {min_c}": bull_c >= min_c,
            f"سيناريو (MARKET/NEAR)": scen in ENTRY_SCENARIOS_ALLOWED,
            f"ADX ≥ {min_adx}": adx_v >= min_adx,
            f"حجم نسبي ≥ {min_rv}": rel_v >= min_rv,
            "السعر فوق SMA50": above_sma,
            "لم ترسل OPEN من قبل": not was_sent(sym, "OPEN"),
        }

        all_ok = all(conditions.values())
        met = [k for k, v in conditions.items() if v]

        if all_ok:
            reason = f"🧪 اختبار — {len(met)}/{len(conditions)} شرط مستوفاة: {', '.join(met[:4])}..."
            card = build_signal_card(sym, v, a, t, "OPEN", reason, settings)
            card["test"] = True

            if engine:
                engine._push_signal(card)
            else:
                log_signal({
                    "symbol": card.get("symbol", ""),
                    "action": card.get("action", ""),
                    "price": card.get("price"),
                    "reason": card.get("reason", ""),
                    "score": card.get("score", 0.0),
                    "signal_type": card.get("signal", ""),
                })

            triggered.append(sym)
            count += 1

    return {
        "ok": True,
        "triggered": triggered,
        "msg": f"تم إطلاق {len(triggered)} إشارة تجريبية (بشروط الطيار الآلي)",
    }


# ═══════════════════════════════════════════════════════════════
# 18. GET /api/auto/signals/log — سجل الإشارات
# Signal history
# ═══════════════════════════════════════════════════════════════


@router.get("/api/auto/signals/log")
async def get_signal_log(user: Dict = Depends(require_premium)):
    """جلب سجل الإشارات التاريخية"""
    log = load_signals_log()
    return {"ok": True, "log": log, "count": len(log)}


# ═══════════════════════════════════════════════════════════════
# 19. GET /api/performance — تحليل الأداء
# Trading performance analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/performance")
async def get_performance(user: Dict = Depends(require_premium)):
    """تحليل أداء التداولات المغلقة"""
    return _analyze_performance()


# ═══════════════════════════════════════════════════════════════
# 20. GET /api/backtest — تحليل الباك تيست
# Backtest analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/backtest")
async def get_backtest(user: Dict = Depends(require_premium)):
    """تحليل أداء الإشارات المسجلة (باك تيست)"""
    signals = load_signals_log(limit=500)
    open_signals = [s for s in signals if s.get("action") == "OPEN"]
    closed_signals = [s for s in open_signals if s.get("result") in ("WIN", "LOSS")]

    total = len(closed_signals)
    wins = sum(1 for s in closed_signals if s.get("result") == "WIN")
    losses = sum(1 for s in closed_signals if s.get("result") == "LOSS")
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    total_pnl = sum(s.get("pnl", 0) or 0 for s in closed_signals)
    avg_win = sum(s.get("pnl", 0) or 0 for s in closed_signals if s.get("result") == "WIN")
    avg_win = round(avg_win / wins, 2) if wins > 0 else 0
    avg_loss = sum(s.get("pnl", 0) or 0 for s in closed_signals if s.get("result") == "LOSS")
    avg_loss = round(avg_loss / losses, 2) if losses > 0 else 0

    total_wins_pnl = sum(s.get("pnl", 0) or 0 for s in closed_signals if s.get("result") == "WIN")
    total_losses_pnl = abs(sum(s.get("pnl", 0) or 0 for s in closed_signals if s.get("result") == "LOSS"))
    profit_factor = round(total_wins_pnl / total_losses_pnl, 2) if total_losses_pnl > 0 else 0

    # آخر 20 إشارة
    recent = sorted(closed_signals, key=lambda s: s.get("created_at", ""), reverse=True)[:20]

    return {
        "ok": True,
        "stats": {
            "total_signals": len(open_signals),
            "closed_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
        },
        "recent": recent,
    }


# ═══════════════════════════════════════════════════════════════
# 21. GET /api/breadth — تحليل اتساع السوق
# Market breadth analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/breadth")
async def get_breadth():
    """تحليل اتساع السوق — الأسهم الصاعدة/الهابطة + متوسط RSI"""
    dm = get_data_manager()
    stocks = dm.get_stocks()
    d: Dict[str, Any] = {}

    # تحويل إلى قواميس مع التحليل
    for sym, stock_data in stocks.items():
        v = stock_data.to_dict() if hasattr(stock_data, "to_dict") else stock_data
        if v.get("analysis") is None and v.get("price"):
            v["analysis"] = analyze_stock(sym, v)
        d[sym] = v

    adv = sum(1 for v in d.values() if (v.get("change_pct") or 0) > 0)
    dec = sum(1 for v in d.values() if (v.get("change_pct") or 0) < 0)
    unc = len(d) - adv - dec
    total = len(d) or 1

    # متوسط RSI
    rsi_vals = [v.get("rsi") for v in d.values() if v.get("rsi")]
    avg_rsi = round(sum(rsi_vals) / len(rsi_vals), 1) if rsi_vals else None

    # نسبة الأسهم فوق المتوسطات
    above_sma50 = sum(
        1 for v in d.values()
        if v.get("price") and v.get("sma50") and v["price"] > v["sma50"]
    )
    above_sma200 = sum(
        1 for v in d.values()
        if v.get("price") and v.get("sma200") and v["price"] > v["sma200"]
    )

    # إشارات شراء وبيع
    buy_signals = sum(
        1 for v in d.values()
        if v.get("analysis", {}).get("signal_type", "") in
        ("BUY_STRONG", "BUY", "ACCUMULATE")
    )
    sell_signals = sum(
        1 for v in d.values()
        if v.get("analysis", {}).get("signal_type", "") in
        ("SELL_STRONG", "SELL")
    )

    # تقييم اتجاه السوق
    adv_ratio = adv / total * 100
    if adv_ratio >= 70:
        mkt_mood = "صاعد قوي 🚀"
    elif adv_ratio >= 55:
        mkt_mood = "صاعد ↑"
    elif adv_ratio >= 45:
        mkt_mood = "محايد ↔"
    elif adv_ratio >= 30:
        mkt_mood = "هابط ↓"
    else:
        mkt_mood = "هابط قوي 📉"

    # تحذيرات الاتساع
    breadth_warning: Optional[str] = None
    if adv_ratio < 25:
        breadth_warning = "⚠️ 75%+ من الأسهم هابطة — إشارات الشراء محفوفة بمخاطرة عالية"
    elif adv_ratio > 80:
        breadth_warning = "⚠️ السوق في تشبع صعودي — كن حذراً في الدخول"

    # بيانات EGX30
    mstatus, mcode = market_status()
    egx30_price, egx30_chg = None, None
    try:
        egx30_price, egx30_chg = dm._source.fetch_index("EGX30")
    except Exception:
        pass

    # أكبر صعود/هبوط
    gainers = sorted(
        [
            {
                "sym": s,
                "chg": v.get("change_pct", 0),
                "price": v.get("price"),
                "vol": v.get("volume"),
                "sector": v.get("sector", ""),
                "vs_egx30": v.get("analysis", {}).get("vs_egx30"),
            }
            for s, v in d.items()
            if v.get("change_pct") is not None
        ],
        key=lambda x: x["chg"],
        reverse=True,
    )

    # أداء القطاعات
    sector_perf: Dict[str, Dict[str, float]] = {}
    for sym, v in d.items():
        sec = v.get("sector", "أخرى")
        chg = v.get("change_pct") or 0
        if sec not in sector_perf:
            sector_perf[sec] = {"sum": 0, "count": 0}
        sector_perf[sec]["sum"] += chg
        sector_perf[sec]["count"] += 1

    sector_avg = {
        s: round(v["sum"] / v["count"], 2)
        for s, v in sector_perf.items()
        if v["count"] > 0
    }

    return {
        "ok": True,
        "total": total,
        "advancing": adv,
        "declining": dec,
        "unchanged": unc,
        "adv_ratio": round(adv_ratio, 1),
        "avg_rsi": avg_rsi,
        "above_sma50_pct": round(above_sma50 / total * 100, 1),
        "above_sma200_pct": round(above_sma200 / total * 100, 1),
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "market_mood": mkt_mood,
        "warning": breadth_warning,
        "entry_time": calc_optimal_entry_time(),
        # بيانات إضافية من النسخة الأصلية
        "market_status": mstatus,
        "market_code": mcode,
        "is_open": is_trading_hours(),
        "egx30_price": egx30_price,
        "egx30_chg": egx30_chg,
        "top_gainers": gainers[:10],
        "top_losers": gainers[-10:][::-1],
        "sector_perf": sector_avg,
        "total_stocks": len(d),
    }


# ═══════════════════════════════════════════════════════════════
# 20b. GET /api/market — بيانات السوق (واجهة التوافق مع الواجهة الأمامية)
# Market data (frontend compatibility endpoint)
# ═══════════════════════════════════════════════════════════════


@router.get("/api/market")
async def get_market():
    """بيانات السوق الشاملة — يعيد بيانات السوق بتنسيق متوافق مع الواجهة الأمامية"""
    dm = get_data_manager()
    stocks = dm.get_stocks()

    if not stocks:
        return {"ok": False, "error": "لا توجد بيانات بعد — اضغط تحديث"}

    # تحويل بيانات الأسهم لقواميس للتحليل
    d: Dict[str, Any] = {}
    for sym, stk in stocks.items():
        d[sym] = stk.to_dict() if hasattr(stk, 'to_dict') else {
            "change_pct": getattr(stk, 'change_pct', None),
            "price": getattr(stk, 'price', None),
            "volume": getattr(stk, 'volume', None),
            "sector": getattr(stk, 'sector', ''),
            "rsi": getattr(stk, 'rsi', None),
            "analysis": getattr(stk, 'analysis', {}),
        }

    advancers = decliners = unchanged = 0
    rsi_values = []
    gainers = []

    for sym, v in d.items():
        chg = v.get("change_pct") or 0
        if chg > 0:
            advancers += 1
        elif chg < 0:
            decliners += 1
        else:
            unchanged += 1

        rsi_val = v.get("rsi")
        if rsi_val is not None:
            rsi_values.append(rsi_val)

        analysis = v.get("analysis", {})
        gainers.append({
            "sym": sym,
            "chg": round(chg, 2),
            "price": v.get("price"),
            "vol": v.get("volume"),
            "sector": v.get("sector", ""),
            "vs_egx30": analysis.get("vs_egx30") if isinstance(analysis, dict) else None,
        })

    gainers.sort(key=lambda x: x["chg"], reverse=True)
    avg_rsi = round(sum(rsi_values) / len(rsi_values), 1) if rsi_values else 50

    # أداء القطاعات (للهيت ماب)
    sector_perf: Dict[str, Dict[str, float]] = {}
    for sym, v in d.items():
        sec = v.get("sector", "أخرى")
        chg = v.get("change_pct") or 0
        if sec not in sector_perf:
            sector_perf[sec] = {"sum": 0, "count": 0}
        sector_perf[sec]["sum"] += chg
        sector_perf[sec]["count"] += 1

    sector_avg = {
        s: round(v["sum"] / v["count"], 2)
        for s, v in sector_perf.items()
        if v["count"] > 0
    }

    mstatus, mcode = market_status()
    egx30_price, egx30_chg = None, None
    try:
        egx30_price, egx30_chg = dm._source.fetch_index("EGX30")
    except Exception:
        pass

    return {
        "ok": True,
        "market_status": mstatus,
        "market_code": mcode,
        "is_open": is_trading_hours(),
        "egx30_price": egx30_price,
        "egx30_chg": egx30_chg,
        "advancing": advancers,
        "declining": decliners,
        "unchanged": unchanged,
        "avg_rsi": avg_rsi,
        "top_gainers": gainers[:10],
        "top_losers": gainers[-10:][::-1],
        "sector_perf": sector_avg,
        "total_stocks": len(d),
    }


# ═══════════════════════════════════════════════════════════════
# 21. POST /api/auth/login — تسجيل الدخول
# JWT Login
# ═══════════════════════════════════════════════════════════════


@router.post("/api/auth/login")
async def login(body: LoginRequest):
    """تسجيل الدخول — أدمن (من الإعدادات) أو مستخدم عادي (من جدول users)"""
    settings = load_settings()
    admin_hash = settings.get("password_hash")
    email = body.email.strip().lower()

    # 0. وضع المستخدم الواحد (لا توجد كلمة مرور) — اسمح بالدخول المباشر
    if not admin_hash:
        token = create_jwt_token(user_id=email, role="admin")
        return {"ok": True, "token": token, "role": "admin", "single_user": True}

    # 1. محاولة تسجيل دخول الأدمن
    admin_user = settings.get("auth_username", "admin")
    admin_email = settings.get("auth_email", "admin@example.com")
    if admin_hash and (email == admin_email or email == admin_user):
        if verify_password(body.password, admin_hash):
            token = create_jwt_token(user_id=email, role="admin")
            return {"ok": True, "token": token, "role": "admin"}

    # 2. محاولة تسجيل دخول مستخدم عادي بالايميل
    from database import get_user_by_email
    user = get_user_by_email(email)
    if user and user.get("is_active", True) and verify_password(body.password, user["password_hash"]):
        token = create_jwt_token(user_id=email, role=user["role"])
        return {"ok": True, "token": token, "role": user["role"], "user": user}

    raise HTTPException(status_code=401, detail="البريد الإلكتروني أو كلمة المرور غير صحيحة")


class RegisterRequest(BaseModel):
    """طلب تسجيل مستخدم جديد"""
    username: str = Field(..., min_length=2, max_length=50, description="اسم المستخدم")
    email: str = Field(..., description="البريد الإلكتروني")
    password: str = Field(..., min_length=6, description="كلمة المرور (6 أحرف على الأقل)")


@router.post("/api/auth/register")
async def register(body: RegisterRequest):
    """تسجيل مستخدم جديد (دور: user) — تأكيد تلقائي (فترة تجريبية)"""
    from database import register_user
    hashed = hash_password(body.password)
    user = register_user(body.username.strip(), body.email.strip().lower(), hashed, "user", confirmed=True)
    if not user:
        raise HTTPException(status_code=400, detail="اسم المستخدم أو البريد الإلكتروني موجود بالفعل")

    jwt_token = create_jwt_token(user_id=body.email.strip().lower(), role="user")
    return {"ok": True, "token": jwt_token, "role": "user", "user": user, "email_confirmed": True}


# ═══════════════════════════════════════════════════════════════
# 22. POST /api/auth/setup — إعداد كلمة المرور لأول مرة
# Initial password setup
# ═══════════════════════════════════════════════════════════════


@router.post("/api/auth/setup")
async def setup_password(body: SetupRequest):
    """إعداد كلمة المرور لأول مرة"""
    settings = load_settings()

    if settings.get("password_hash"):
        raise HTTPException(
            status_code=400,
            detail="تم تعيين كلمة المرور بالفعل — استخدم /api/auth/login",
        )

    # تجزئة كلمة المرور وحفظها مع الإيميل
    hashed = hash_password(body.password)
    save_settings({"password_hash": hashed, "auth_email": body.email})

    # إنشاء رمز JWT
    token = create_jwt_token(user_id=body.email, role="admin")
    return {"ok": True, "token": token, "msg": "تم تعيين كلمة المرور بنجاح"}


# ═══════════════════════════════════════════════════════════════
# 22b. POST /api/auth/set-password — تعيين أو إزالة كلمة المرور
# Set or remove password (unified endpoint for UI)
# ═══════════════════════════════════════════════════════════════


class SetPasswordRequest(BaseModel):
    """تعيين/تغيير/إزالة كلمة المرور"""
    current_password: str = ""
    new_password: str = ""
    username: Optional[str] = None
    auth_email: Optional[str] = None


@router.get("/api/auth/me")
async def auth_me(user: Dict = Depends(get_current_user)):
    """معلومات المستخدم الحالي"""
    username = user.get("sub", "")
    from database import get_user_by_email
    db_user = get_user_by_email(username) if '@' in username else None
    plan = user.get("plan", "free")
    email_confirmed = db_user.get("email_confirmed", False) if db_user else True
    return {"ok": True, "user": {"email": username, "role": user.get("role"), "plan": plan, "email_confirmed": email_confirmed}}


@router.get("/api/auth/confirm-email")
async def confirm_email(token: str = Query(..., description="رمز التأكيد")):
    """تأكيد البريد الإلكتروني"""
    from database import confirm_email as db_confirm
    if db_confirm(token):
        from fastapi.responses import HTMLResponse
        return HTMLResponse("""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>تم التأكيد</title></head><body style="background:#0a0e1a;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center"><div><h2 style="color:#00e676">✅ تم تأكيد البريد الإلكتروني بنجاح!</h2><p style="color:#94a3b8">يمكنك إغلاق هذه الصفحة والعودة للتطبيق</p></div></body></html>""")
    raise HTTPException(status_code=400, detail="رمز التأكيد غير صالح أو منتهي الصلاحية")


@router.post("/api/auth/set-password")
async def set_password_endpoint(body: SetPasswordRequest):
    """تعيين أو تغيير أو إزالة كلمة المرور"""
    settings = load_settings()
    existing_hash = settings.get("password_hash")

    # إذا كانت كلمة المرور الجديدة فارغة → إزالة كلمة المرور
    if not body.new_password:
        if existing_hash:
            # التحقق من كلمة المرور الحالية قبل الإزالة
            if not verify_password(body.current_password, existing_hash):
                raise HTTPException(status_code=401, detail="كلمة المرور الحالية غير صحيحة")
            save_settings({"password_hash": ""})
            return {"ok": True, "msg": "تم إزالة كلمة المرور"}
        return {"ok": True, "msg": "لا توجد كلمة مرور لإزالتها"}

    # تعيين أو تغيير كلمة المرور
    if existing_hash:
        # تغيير — التحقق من الحالية أولاً
        if not verify_password(body.current_password, existing_hash):
            raise HTTPException(status_code=401, detail="كلمة المرور الحالية غير صحيحة")

    update = {"password_hash": hash_password(body.new_password)}
    if body.username:
        update["auth_username"] = body.username
    if body.auth_email:
        update["auth_email"] = body.auth_email
    save_settings(update)

    token = create_jwt_token(user_id=body.auth_email or body.username or "admin", role="admin")
    return {"ok": True, "token": token, "msg": "تم تعيين كلمة المرور بنجاح"}


# ═══════════════════════════════════════════════════════════════
# 23. GET /api/engine/status — حالة محرك القرار
# Decision engine status
# ═══════════════════════════════════════════════════════════════


@router.get("/api/engine/status")
async def get_engine_status(user: Dict = Depends(require_premium)):
    """جلب حالة محرك القرار التلقائي"""
    engine = get_engine()

    if engine is None:
        return {
            "ok": True,
            "initialized": False,
            "running": False,
            "mode": "none",
        }

    return {
        "ok": True,
        "initialized": True,
        "running": engine.is_running,
        "mode": engine.mode,
        "interval": engine.interval,
        "daily_loss_limit": engine.daily_loss_limit,
        "daily_pnl": engine.daily_pnl,
        "pending_approvals": len(engine.pending_approvals),
        "signals_count": len(engine.signals),
    }


# ═══════════════════════════════════════════════════════════════
# 24. POST /api/engine/start — بدء محرك القرار
# Start decision engine
# ═══════════════════════════════════════════════════════════════


@router.get("/api/engine/check/{symbol}")
async def check_engine_eligibility(symbol: str, user: Dict = Depends(require_premium)):
    """تشخيص: ليه السهم مش شغال في الطيار الآلي؟"""
    try:
        from analysis import BUY_SIGNALS, ENTRY_SCENARIOS_ALLOWED
        from database import was_sent, load_settings, load_trades

        dm = get_data_manager()
        stocks = dm.get_stocks()
        if not stocks or symbol not in stocks:
            return {"ok": False, "msg": "رمز السهم غير موجود", "symbol": symbol}

        v = stocks[symbol].to_dict() if hasattr(stocks[symbol], "to_dict") else stocks[symbol]
        if v.get("analysis") is None and v.get("price"):
            from analysis import analyze_stock
            v["analysis"] = analyze_stock(symbol, v)
        a = v.get("analysis") or {}
        t = a.get("trade") or {}

        settings = load_settings()
        trades = load_trades()
        open_trades = {tr["symbol"]: tr for tr in trades if tr.get("status") == "active"}
        open_count = len(open_trades)

        min_quality = settings.get("min_quality", 70)
        min_rr = settings.get("min_rr", 1.5)
        min_liq = settings.get("min_liq", 40)
        min_confirm = settings.get("min_confirm", 3)
        min_adx = settings.get("min_adx", 20)
        min_rel_vol = settings.get("min_rel_vol", 1.2)

        price = v.get("price", 0)
        sig_type = a.get("signal_type", "")
        tq = t.get("trade_quality", 0) or 0
        rr1_val = t.get("rr1", 0) or 0
        liq = t.get("liq_score", 0) or 0
        bull_c = (a.get("confirmation", {}) or {}).get("bull_count", 0)
        scen = t.get("entry_scenario", "WAIT")
        adx_val = v.get("adx") or 0
        avg_vol = v.get("avg_vol", 0) or 0
        vol = v.get("volume", 0) or 0
        rel_vol = (vol / avg_vol) if avg_vol > 0 else 0
        sma50_val = v.get("sma50")
        price_above_sma50 = (price > sma50_val) if (price and sma50_val) else True

        checks = [
            {"check": "auto_open مفعل", "passed": bool(settings.get("auto_open", False)), "detail": f"auto_open = {settings.get('auto_open')}"},
            {"check": "نوع الإشارة شراء", "passed": sig_type in BUY_SIGNALS, "detail": f"signal_type = {sig_type}"},
            {"check": "جودة الصفقة", "passed": tq >= min_quality, "detail": f"trade_quality = {tq:.1f} (min {min_quality})"},
            {"check": "نسبة المخاطرة/عائد", "passed": rr1_val >= min_rr, "detail": f"RR = {rr1_val:.2f} (min {min_rr})"},
            {"check": "السيولة", "passed": liq >= min_liq, "detail": f"liq_score = {liq} (min {min_liq})"},
            {"check": "عدد المؤشرات", "passed": bull_c >= min_confirm, "detail": f"bull_count = {bull_c} (min {min_confirm})"},
            {"check": "سيناريو الدخول", "passed": scen in ENTRY_SCENARIOS_ALLOWED, "detail": f"scenario = {scen}"},
            {"check": "ADX", "passed": adx_val >= min_adx, "detail": f"ADX = {adx_val:.1f} (min {min_adx})"},
            {"check": "الحجم النسبي", "passed": rel_vol >= min_rel_vol, "detail": f"rel_vol = {rel_vol:.2f} (min {min_rel_vol})"},
            {"check": "السعر فوق SMA50", "passed": price_above_sma50, "detail": f"price={price}, SMA50={sma50_val}"},
            {"check": "تم إرسال OPEN مسبقاً", "passed": not was_sent(symbol, "OPEN"), "detail": f"was_sent = {was_sent(symbol, 'OPEN')}"},
        ]

        engine_ok = all(c["passed"] for c in checks)

        eng = get_engine()
        return {
            "ok": True,
            "symbol": symbol,
            "name": v.get("name_en", symbol),
            "price": price,
            "all_checks_pass": engine_ok,
            "checks": checks,
            "engine": {
                "mode": eng.mode if eng else "unknown",
                "running": eng.is_running if eng else False,
                "daily_pnl": eng.daily_pnl if eng else 0,
            },
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


@router.post("/api/engine/start")
async def start_engine(
    body: Optional[EngineModeUpdate] = None,
    user: Dict = Depends(require_premium),
):
    """بدء محرك القرار التلقائي"""
    global _engine

    if _engine is None:
        dm = get_data_manager()
        settings = load_settings()
        mode = (body.mode if body else None) or settings.get("trade_mode", TRADE_MODE_AUTO)
        daily_limit = settings.get("daily_loss_limit", DEFAULT_DAILY_LOSS_LIMIT)

        _engine = DecisionEngine(
            data_manager=dm,
            mode=mode,
            daily_loss_limit=daily_limit,
        )

    if body and body.mode:
        _engine.mode = body.mode

    _engine.start()
    set_engine(_engine)

    return {
        "ok": True,
        "running": _engine.is_running,
        "mode": _engine.mode,
        "msg": f"تم بدء محرك القرار (الوضع: {_engine.mode})",
    }


# ═══════════════════════════════════════════════════════════════
# 25. POST /api/engine/stop — إيقاف محرك القرار
# Stop decision engine
# ═══════════════════════════════════════════════════════════════


@router.post("/api/engine/stop")
async def stop_engine(user: Dict = Depends(require_premium)):
    """إيقاف محرك القرار التلقائي"""
    engine = get_engine()

    if engine is None or not engine.is_running:
        return {"ok": True, "running": False, "msg": "المحرك متوقف بالفعل"}

    engine.stop()
    return {"ok": True, "running": False, "msg": "تم إيقاف محرك القرار"}


# ═══════════════════════════════════════════════════════════════
# 26. POST /api/engine/approve/{signal_id} — الموافقة على صفقة معلقة
# Approve pending trade (semi-auto mode)
# ═══════════════════════════════════════════════════════════════


@router.post("/api/engine/approve/{signal_id}")
async def approve_signal(signal_id: str, user: Dict = Depends(get_current_user)):
    """الموافقة على إشارة معلقة في وضع شبه تلقائي"""
    engine = get_engine()

    if engine is None:
        raise HTTPException(status_code=400, detail="محرك القرار غير مهيأ")

    with engine._pending_lock:
        pending = engine._pending_approvals
        found_idx = None
        for i, p in enumerate(pending):
            card = p.get("card", {})
            if card.get("id") == signal_id:
                found_idx = i
                break

        if found_idx is None:
            raise HTTPException(status_code=404, detail="الإشارة غير موجودة في قائمة الانتظار")

        # استخراج بيانات الإشارة
        item = pending.pop(found_idx)

    # تنفيذ الإشارة حسب نوعها
    p_type = item.get("type")
    settings = load_settings()

    if p_type == "OPEN":
        sym = item.get("sym")
        t = item.get("t", {})
        a = item.get("a", {})
        v = item.get("v", {})
        trades = load_trades()
        open_trades = {tr["symbol"]: tr for tr in trades if tr.get("status") == "active"}
        engine._open_trade(sym, t, a, v, settings, trades, open_trades)
        logger.info("✅ تمت الموافقة على فتح صفقة: %s", sym)

    elif p_type in ("CLOSE_T1", "CLOSE_T2", "CLOSE_T3", "CLOSE_STOP"):
        trade = item.get("trade", {})
        price = item.get("price", 0)
        ep = item.get("ep", 0)

        if p_type == "CLOSE_STOP":
            pnl_pct = round((price - ep) / ep * 100, 2) if ep else 0
            pnl_egp = round((price - ep) * trade.get("shares", 0), 2) if ep else 0
            engine._daily_pnl += pnl_egp
            trade.update({
                "status": "closed",
                "exit_price": price,
                "exit_date": datetime.utcnow().isoformat(),
                "pnl_pct": pnl_pct,
                "pnl": pnl_egp,
                "exit_reason": "STOP",
            })
            save_trades(load_trades())  # حفظ التحديثات
            logger.info("✅ تمت الموافقة على إغلاق صفقة: %s", trade.get("symbol"))

    return {"ok": True, "msg": f"تمت الموافقة على الإشارة {signal_id}"}


# ═══════════════════════════════════════════════════════════════
# 27. POST /api/engine/reject/{signal_id} — رفض صفقة معلقة
# Reject pending trade
# ═══════════════════════════════════════════════════════════════


@router.post("/api/engine/reject/{signal_id}")
async def reject_signal(signal_id: str, user: Dict = Depends(get_current_user)):
    """رفض إشارة معلقة في وضع شبه تلقائي"""
    engine = get_engine()

    if engine is None:
        raise HTTPException(status_code=400, detail="محرك القرار غير مهيأ")

    with engine._pending_lock:
        pending = engine._pending_approvals
        found_idx = None
        for i, p in enumerate(pending):
            card = p.get("card", {})
            if card.get("id") == signal_id:
                found_idx = i
                break

        if found_idx is None:
            raise HTTPException(status_code=404, detail="الإشارة غير موجودة في قائمة الانتظار")

        pending.pop(found_idx)

    logger.info("❌ تم رفض الإشارة: %s", signal_id)
    return {"ok": True, "msg": f"تم رفض الإشارة {signal_id}"}


# ══════════════════════════════════════════════════════════════════════════════
# 25. GET /api/analytics — إحصائيات الزوار (للأدمن فقط)
# Visit analytics (admin only)
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/admin/users")
async def get_admin_users(user: Dict = Depends(get_current_user)):
    """قائمة المستخدمين المسجلين (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح")
    from database import get_session, User
    import json
    with get_session() as session:
        users = session.query(User).order_by(User.created_at.desc()).all()
        return {"ok": True, "users": [{"id":u.id, "username":u.username, "email":u.email, "role":u.role, "created_at":str(u.created_at or "")} for u in users]}


@router.post("/api/admin/delete-user")
async def delete_admin_user(body: dict, user: Dict = Depends(get_current_user)):
    """حذف مستخدم (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح")
    from database import get_session, User
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="معرف المستخدم مطلوب")
    with get_session() as session:
        target = session.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="المستخدم غير موجود")
        session.delete(target)
        session.commit()
    return {"ok": True, "detail": "تم حذف المستخدم بنجاح"}


@router.get("/api/analytics")
async def get_analytics(user: Dict = Depends(get_current_user)):
    """إحصائيات شاملة (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح — هذه المعلومات للأدمن فقط")
    from database import get_visit_stats
    return {"ok": True, "stats": get_visit_stats()}


@router.get("/api/analytics/visits")
async def get_visits(user: Dict = Depends(get_current_user)):
    """قائمة الزيارات الأخيرة (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح — هذه المعلومات للأدمن فقط")
    from database import get_all_visits
    return {"ok": True, "visits": get_all_visits(50)}


# ══════════════════════════════════════════════════════════════════════════════
# 26. ملف المستخدم والاشتراك المميز
# User profile & premium subscription
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/user/profile")
async def get_user_profile(user: Dict = Depends(get_current_user)):
    """ملف المستخدم — اسم، بريد، نوع الحساب"""
    from database import get_user_by_email
    uid = user.get("sub", "admin")
    profile = None
    if '@' in uid:
        profile = get_user_by_email(uid)
    if not profile:
        from database import get_user_by_username
        profile = get_user_by_username(uid)
    if not profile:
        # لو مش في DB (admin من الإعدادات) اعمل profile افتراضي
        settings = load_settings()
        return {
            "ok": True,
            "user": {
                "username": uid,
                "email": settings.get("auth_email", uid),
                "role": user.get("role", "admin"),
                "plan": "premium" if uid in ("admin", settings.get("auth_email", "")) else "free",
                "premium_until": None,
                "email_confirmed": True,
                "is_active": True,
            }
        }
    return {"ok": True, "user": profile}


@router.post("/api/user/apply-code")
async def apply_premium_code_ep(body: dict, user: Dict = Depends(get_current_user)):
    """تطبيق كود اشتراك مميز"""
    code = body.get("code", "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="الكود مطلوب")
    from database import apply_premium_code
    uid = user.get("sub", "admin")
    result = apply_premium_code(uid, code)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["detail"])
    return {"ok": True, "plan": result["plan"], "premium_until": result["premium_until"]}


@router.post("/api/user/cancel-premium")
async def cancel_premium_ep(user: Dict = Depends(get_current_user)):
    """إلغاء الاشتراك المميز"""
    from database import cancel_premium
    uid = user.get("sub", "admin")
    ok = cancel_premium(uid)
    if not ok:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    return {"ok": True, "plan": "free"}


@router.post("/api/admin/generate-codes")
async def generate_codes_ep(body: dict, user: Dict = Depends(get_current_user)):
    """توليد أكواد اشتراك مميز (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح")
    count = body.get("count", 1)
    duration = body.get("duration_days", 30)
    max_uses = body.get("max_uses", 1)
    from database import generate_premium_codes
    codes = generate_premium_codes(count=count, duration_days=duration,
                                   max_uses=max_uses, created_by=user.get("sub"))
    return {"ok": True, "codes": codes}


@router.get("/api/admin/codes")
async def get_codes_ep(user: Dict = Depends(get_current_user)):
    """قائمة أكواد الاشتراك (للأدمن فقط)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح")
    from database import get_premium_codes
    return {"ok": True, "codes": get_premium_codes()}


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Application - التطبيق الرئيسي
# ══════════════════════════════════════════════════════════════════════════════
