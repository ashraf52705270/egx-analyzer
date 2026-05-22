import sys, os, json, logging, time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

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
DEFAULT_COMMISSION_PCT = 0.6  # % جولة كاملة (شراء + بيع)

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


def _calc_commission(entry: float, exit_: float, shares: int, settings: dict) -> float:
    """حساب مصاريف التداول للجولة كاملة (شراء + بيع)"""
    pct = float(settings.get("commission_pct", DEFAULT_COMMISSION_PCT))
    return round((entry + exit_) * shares * pct / 200, 2)


class DecisionEngine:
    """
    محرك القرار التلقائي — يعمل في خيط خلفي كل 30 ثانية
    Automated Decision Engine — runs in background thread every 30 seconds

    الأوضاع الثلاثة:
    - AUTO: تنفيذ تلقائي كامل (فتح وإغلاق صفقات)
    - SEMI_AUTO: يرسل إشارات ويحتاج موافقة المستخدم للتنفيذ
    - MANUAL: يرسل إشارات فقط بدون أي تنفيذ تلقائي

    الميزات:
    - حد خسارة يومي (Daily Loss Limit) — يتوقف عن التداول عند بلوغه
    - وقف خسارة متحرك (Trailing Stop) — يُحرّك الوقف عند بلوغ الأهداف
    - منع تكرار الإشارات (Dedup) — لا يرسل نفس الإشارة مرتين في نفس اليوم
    - تسجيل الإشارات في قاعدة البيانات
    """

    def __init__(
        self,
        data_manager: DataManager,
        interval: int = ENGINE_INTERVAL,
        mode: str = TRADE_MODE_AUTO,
        daily_loss_limit: float = DEFAULT_DAILY_LOSS_LIMIT,
    ) -> None:
        """
        تهيئة محرك القرار

        المعطيات:
            data_manager:     مدير البيانات لجلب بيانات الأسهم
            interval:         الفترة الزمنية بين الدورات بالثواني (الافتراضي: 30)
            mode:             وضع التداول (auto / semi_auto / manual)
            daily_loss_limit: حد الخسارة اليومي كنسبة من رأس المال (الافتراضي: 5%)
        """
        self._data_manager = data_manager
        self._interval = interval
        self._mode = mode
        self._daily_loss_limit = daily_loss_limit

        # خيط التنفيذ الخلفي
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # قائمة الإشارات في الذاكرة (الأحدث أولاً)
        self._signals: List[Dict[str, Any]] = []
        self._signals_lock = threading.Lock()

        # حالة السوق — كشف الصرف/التجميع الجماعي
        self._market_distribution: Dict[str, Any] = {
            "state": "عادي", "distribution": False, "accumulation": False,
            "severity": 0, "level": "عادي", "advancing_pct": 50, "warnings": [],
        }

        # تتبع الخسارة اليومية
        self._daily_pnl: float = 0.0
        self._daily_pnl_date: str = ""

        # تتبع الخسائر المتتالية
        self._consecutive_losses: int = 0
        self._max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES

        # إشارات تحتاج موافقة (في وضع SEMI_AUTO فقط)
        self._pending_approvals: List[Dict[str, Any]] = []
        self._pending_lock = threading.Lock()

        # رد نداء الإشارات (يُستدعى عند كل إشارة جديدة)
        self._on_signal_callback: Optional[Callable[[Dict[str, Any]], None]] = None

        logger.info(
            "تم تهيئة محرك القرار (الوضع: %s، الفترة: %d ثانية، حد الخسارة اليومي: %.1f%%)",
            mode, interval, daily_loss_limit,
        )

    # ══════════════════════════════════════════════════════════════
    # خصائص عامة
    # Public Properties
    # ══════════════════════════════════════════════════════════════

    @property
    def is_running(self) -> bool:
        """هل المحرك يعمل؟"""
        return self._thread is not None and self._thread.is_alive()

    @property
    def mode(self) -> str:
        """وضع التداول الحالي"""
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        """
        تعيين وضع التداول

        المعطيات:
            value: الوضع الجديد (auto / semi_auto / manual)
        """
        if value not in (TRADE_MODE_AUTO, TRADE_MODE_SEMI, TRADE_MODE_MANUAL):
            raise ValueError(f"وضع تداول غير صالح: '{value}'. الأوضاع المتاحة: auto, semi_auto, manual")
        self._mode = value
        logger.info("تم تغيير وضع التداول إلى: %s", value)

    @property
    def market_distribution(self) -> Dict[str, Any]:
        """حالة صرف السوق الحالية"""
        return self._market_distribution

    @property
    def daily_loss_limit(self) -> float:
        """حد الخسارة اليومي كنسبة من رأس المال"""
        return self._daily_loss_limit

    @daily_loss_limit.setter
    def daily_loss_limit(self, value: float) -> None:
        """تعيين حد الخسارة اليومي"""
        if value <= 0:
            raise ValueError("حد الخسارة اليومي يجب أن يكون موجباً")
        self._daily_loss_limit = value
        logger.info("تم تحديث حد الخسارة اليومي إلى: %.1f%%", value)

    @property
    def interval(self) -> int:
        """الفترة الزمنية بين الدورات بالثواني"""
        return self._interval

    @interval.setter
    def interval(self, value: int) -> None:
        """تعيين الفترة الزمنية"""
        if value < 5:
            raise ValueError("الفترة الزمنية يجب أن تكون 5 ثوان على الأقل")
        self._interval = value
        logger.info("تم تحديث الفترة الزمنية إلى: %d ثانية", value)

    @property
    def signals(self) -> List[Dict[str, Any]]:
        """قائمة الإشارات في الذاكرة (الأحدث أولاً)"""
        with self._signals_lock:
            return list(self._signals)

    @property
    def pending_approvals(self) -> List[Dict[str, Any]]:
        """قائمة الإشارات التي تحتاج موافقة (في وضع SEMI_AUTO)"""
        with self._pending_lock:
            return list(self._pending_approvals)

    @property
    def daily_pnl(self) -> float:
        """الربح/الخسارة التراكمي لليوم الحالي"""
        self._reset_daily_pnl_if_new_day()
        return self._daily_pnl

    # ══════════════════════════════════════════════════════════════
    # رد نداء الإشارات
    # Signal Callback
    # ══════════════════════════════════════════════════════════════

    def set_on_signal_callback(self, callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """
        تعيين دالة رد نداء تُستدعى عند كل إشارة جديدة

        المعطيات:
            callback: دالة تستقبل قاموس الإشارة كمعطى، أو None لإزالة رد النداء
        """
        self._on_signal_callback = callback
        logger.info("تم %s رد نداء الإشارات", "تعيين" if callback else "إزالة")

    # ══════════════════════════════════════════════════════════════
    # بدء وإيقاف المحرك
    # Start and Stop Engine
    # ══════════════════════════════════════════════════════════════

    def start(self) -> None:
        """
        بدء محرك القرار في خيط خلفي
        Start the decision engine in a background thread

        الأخطاء:
            RuntimeError: إذا كان المحرك يعمل بالفعل
        """
        if self.is_running:
            logger.warning("محرك القرار يعمل بالفعل — يتم التجاهل")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="DecisionEngine",
            daemon=True,
        )
        self._thread.start()
        logger.info("🟢 تم بدء محرك القرار (الوضع: %s)", self._mode)

    def stop(self) -> None:
        """
        إيقاف محرك القرار
        Stop the decision engine

        ينتظر انتهاء الخيط الحالي بأمان.
        """
        if not self.is_running:
            logger.warning("محرك القرار متوقف بالفعل — يتم التجاهل")
            return

        self._stop_event.set()
        self._thread.join(timeout=10)
        logger.info("🔴 تم إيقاف محرك القرار")

    # ══════════════════════════════════════════════════════════════
    # حلقة التنفيذ الرئيسية
    # Main Execution Loop
    # ══════════════════════════════════════════════════════════════

    def _run_loop(self) -> None:
        """
        حلقة التنفيذ الرئيسية — تعمل في الخيط الخلفي
        Main execution loop — runs in the background thread

        تعمل هذه الدالة في حلقة لا نهائية:
        1. الانتظار للفترة المحددة
        2. التحقق من ساعات التداول
        3. تحميل الإعدادات والصفقات
        4. فحص كل سهم لاتخاذ القرارات
        5. حفظ التغييرات
        """
        while not self._stop_event.is_set():
            # الانتظار مع إمكانية الإيقاف الفوري
            if self._stop_event.wait(timeout=self._interval):
                break

            try:
                self._execute_cycle()
            except Exception as e:
                logger.error("✗ خطأ في دورة محرك القرار: %s", e, exc_info=True)

    def _execute_cycle(self) -> None:
        """
        تنفيذ دورة واحدة من محرك القرار
        Execute one cycle of the decision engine
        """
        # التحقق من ساعات التداول
        settings = load_settings()
        if not settings.get("test_mode", False) and not is_trading_hours():
            return

        # جلب البيانات الحالية
        stocks = self._data_manager.get_stocks()
        if not stocks:
            return

        # التحقق من تفعيل المحرك
        if not settings.get("auto_open") and not settings.get("auto_close"):
            return

        # كشف الصرف/التجميع الجماعي
        self._market_distribution = detect_market_distribution(stocks)
        dist = self._market_distribution
        if dist["distribution"]:
            logger.warning(
                "⚠️ صرف جماعي في السوق (الشدة: %d/%d) — %s",
                dist["severity"], 5, " | ".join(dist["warnings"]),
            )
            if dist["severity"] >= 4:
                logger.warning("🚫 تعليق فتح صفقات جديدة بسبب الصرف الجماعي الشديد")
        elif dist["accumulation"]:
            logger.info(
                "✅ تجميع سوقي (الشدة: %d/5) — وقت مناسب لفتح صفقات",
                dist["severity"],
            )

        # تحميل الإعدادات والصفقات
        trades = load_trades()
        open_trades = {tr["symbol"]: tr for tr in trades if tr.get("status") == "active"}

        # قراءة عتبات الإعدادات
        min_quality = settings.get("min_quality", DEFAULT_MIN_QUALITY)
        min_rr      = settings.get("min_rr", DEFAULT_MIN_RR)
        min_liq     = settings.get("min_liq", DEFAULT_MIN_LIQUIDITY)
        min_confirm = settings.get("min_confirm", DEFAULT_MIN_CONFIRMATION)
        min_adx     = settings.get("min_adx", DEFAULT_MIN_ADX)
        min_rel_vol = settings.get("min_rel_vol", DEFAULT_MIN_REL_VOL)

        # تخفيف العتبات أثناء التجميع السوقي
        if dist["accumulation"] and dist["severity"] >= 3:
            min_quality = max(50, min_quality - 10)
            min_rr      = max(1.2, min_rr - 0.3)
            min_liq     = max(25, min_liq - 10)
            min_confirm = max(2, min_confirm - 1)
            min_adx     = max(12, min_adx - 5)
            min_rel_vol = max(0.3, min_rel_vol - 0.2)
            logger.info("✅ تخفيف عتبات الدخول بسبب التجميع السوقي (جودة≥%d, RR≥%.1f)", min_quality, min_rr)

        # منع فتح صفقات أثناء الصرف الشديد (بعد العتبات المعدلة)
        block_new = dist["distribution"] and dist["severity"] >= 4

        # كشف نظام السوق لحساب ml_confidence بشكل متسق مع api/top
        market_regime = detect_market_regime(stocks)

        changed = False
        opened_this_cycle: set = set()
        trade_seq = 0

        # ══════════════════════════════════════════════════════════════
        # فحص كل سهم لاتخاذ القرارات
        # ══════════════════════════════════════════════════════════════
        for sym, stock_data in stocks.items():
            # تحويل StockData إلى قاموس للتوافق مع الدوال الحالية
            v = stock_data.to_dict() if hasattr(stock_data, "to_dict") else stock_data

            a = v.get("analysis")
            if not a:
                a = analyze_stock(sym, v)
                if not a:
                    continue
                v["analysis"] = a
            # إعادة حساب ml_confidence مع نظام السوق (نفس منطق _get_stocks_with_analysis)
            if a:
                tf = a.get("timeframe_alignment")
                harm = a.get("harmonic_pattern")
                ml = calculate_ml_confidence(v, a, regime=market_regime, tf=tf, harmonic=harm)
                kelly = calculate_kelly_size(
                    ml["ml_score"],
                    a.get("trade", {}).get("rr1", 1.0),
                    a.get("trade", {}).get("risk_pct", 2.0),
                    settings.get("capital", DEFAULT_CAPITAL),
                )
                a["ml_confidence"] = ml
                a["kelly"] = kelly
            t     = a.get("trade", {})
            price = v.get("price", 0)
            if not price:
                continue

            # استخراج متغيرات القرار
            sig_type = a.get("signal_type", "")
            tq       = t.get("trade_quality", 0) or 0
            rr1_val  = t.get("rr1", 0) or 0
            liq      = t.get("liq_score", 0) or 0
            conf     = a.get("confirmation", {})
            bull_c   = conf.get("bull_count", 0)
            scen     = t.get("entry_scenario", "WAIT")

            # ════════════════════════════════════════════════════════
            # فلاتر: ADX, حجم نسبي, اتجاه السعر
            # ════════════════════════════════════════════════════════
            adx_val    = v.get("adx") or 0
            rel_vol    = (v.get("volume", 0) / v.get("avg_vol", 1)) if (v.get("avg_vol") or 0) > 0 else 0
            price_ma   = v.get("price", 0)
            sma50_val  = v.get("sma50")
            price_above_sma50 = (price_ma and sma50_val and price_ma > sma50_val) if (price_ma and sma50_val) else True

            # ════════════════════════════════════════════════════════
            # قرار 1: هل نفتح صفقة جديدة؟
            # ════════════════════════════════════════════════════════

            # ════════════════════════════════════════════════════════
            # التحليلات المتقدمة
            # ════════════════════════════════════════════════════════
            ml_score = a.get("ml_confidence", {}).get("ml_score", 50)
            tf_align = a.get("timeframe_alignment", {}).get("alignment_score", 0)
            harmonic_conf = (a.get("harmonic_pattern") or {}).get("confidence", 0) or 0

            # تسجيل سبب رفض السهم (عشان التشخيص)
            if sig_type in BUY_SIGNALS and sym not in open_trades:
                reason = None
                if not settings.get("auto_open"): reason = "auto_open = OFF"
                elif tq < min_quality: reason = f"trade_quality ({tq}) < min ({min_quality})"
                elif rr1_val < min_rr: reason = f"rr1 ({rr1_val}) < min ({min_rr})"
                elif liq < min_liq: reason = f"liq ({liq}) < min ({min_liq})"
                elif bull_c < min_confirm: reason = f"bull_count ({bull_c}) < min ({min_confirm})"
                elif scen not in ENTRY_SCENARIOS_ALLOWED: reason = f"scenario ({scen}) غير مسموح"
                elif not t.get("ready", False): reason = f"السعر خارج نطاق الدخول"
                elif adx_val < min_adx: reason = f"ADX ({adx_val:.1f}) < {min_adx}"
                elif rel_vol < min_rel_vol: reason = f"rel_vol ({rel_vol:.1f}) < {min_rel_vol}"
                elif not price_above_sma50: reason = f"price ({price_ma}) <= SMA50 ({sma50_val})"
                elif ml_score < 35: reason = f"ML ({ml_score}) < 35"
                elif tf_align < -0.6: reason = f"توافق إطارات ({tf_align}) ← عكس الترند"
                elif was_sent(sym, "OPEN"): reason = "تم إرسال إشارة OPEN من قبل"
                if reason:
                    logger.info("  [رفض] %s ← %s", sym, reason)

            # منع إعادة فتح صفقة لنفس السهم لو في صفقة سابقة (أوتوماتيك)
            existing_trade_for_sym = any(
                tr.get("symbol") == sym and tr.get("auto")
                for tr in trades
            )
            # منع فتح صفقات جديدة أثناء الصرف الجماعي الشديد
            if block_new and sig_type in BUY_SIGNALS and sym not in open_trades:
                if not reason:
                    logger.info("  [رفض] %s ← صرف جماعي في السوق (severity=%d)", sym, self._market_distribution["severity"])

            if (
                settings.get("auto_open")
                and sym not in open_trades
                and not existing_trade_for_sym
                and not block_new
                and sig_type in BUY_SIGNALS
                and tq >= min_quality
                and rr1_val >= min_rr
                and liq >= min_liq
                and bull_c >= min_confirm
                and scen in ENTRY_SCENARIOS_ALLOWED
                and t.get("ready", False)
                and ml_score >= 35
                and tf_align >= -0.6
                and adx_val >= min_adx
                and rel_vol >= min_rel_vol
                and price_above_sma50
                and not was_sent(sym, "OPEN")
            ):
                # بناء إشارة الفتح
                card = build_signal_card(
                    sym, v, a, t, ACTION_OPEN,
                    f"زخم قوي — {a.get('signal', '')} ({bull_c} مؤشر)",
                    settings,
                )

                # إرسال الإشارة حسب الوضع
                if self._mode == TRADE_MODE_AUTO:
                    # تنفيذ تلقائي — إرسال الإشارة وفتح الصفقة
                    sig_id = self._push_signal(card)
                    mark_sent(sym, "OPEN")
                    self._open_trade(sym, t, a, v, settings, trades, open_trades, signal_log_id=sig_id, seq=trade_seq)
                    trade_seq += 1
                    opened_this_cycle.add(sym)
                    changed = True

                elif self._mode == TRADE_MODE_SEMI:
                    # شبه تلقائي — إرسال الإشارة وانتظار الموافقة
                    self._push_signal(card)
                    mark_sent(sym, "OPEN")
                    with self._pending_lock:
                        self._pending_approvals.append({
                            "type": "OPEN",
                            "card": card,
                            "sym": sym,
                            "t": t,
                            "a": a,
                            "v": v,
                            "settings": settings,
                        })
                    logger.info("📋 إشارة فتح بانتظار الموافقة: %s @ %.2f", sym, price)

                elif self._mode == TRADE_MODE_MANUAL:
                    # يدوي — إرسال الإشارة فقط بدون تنفيذ
                    self._push_signal(card)
                    mark_sent(sym, "OPEN")
                    logger.info("📡 إشارة فتح (يدوي): %s @ %.2f", sym, price)

            # ════════════════════════════════════════════════════════
            # قرار 2: إدارة الصفقات المفتوحة
            # ════════════════════════════════════════════════════════
            if sym in open_trades and settings.get("auto_close") and sym not in opened_this_cycle:
                tr = open_trades[sym]
                ep = tr.get("entry_price", 0)
                sl = tr.get("stop_loss", 0)

                # ────────────────────────────────────────────────────
                # فحص وقف الخسارة
                # ────────────────────────────────────────────────────
                if sl and price <= sl and not was_sent(sym, "STOP"):
                    card = build_signal_card(
                        sym, v, a, t, ACTION_CLOSE_STOP,
                        f"وصل الوقف {sl} ج",
                        settings,
                    )

                    if self._mode == TRADE_MODE_AUTO:
                        self._push_signal(card)
                        mark_sent(sym, "STOP")
                        # غلق الصفقة
                        pnl_pct = round((price - ep) / ep * 100, 2) if ep else 0
                        pnl_egp = round((price - ep) * tr.get("shares", 0), 2) if ep else 0
                        # خصم مصاريف التداول (افتراضي 0.6% جولة كاملة)
                        comm = _calc_commission(ep, price, tr.get("shares", 0), settings)
                        pnl_egp -= comm
                        self._daily_pnl += pnl_egp
                        # تتبع الخسائر المتتالية
                        if pnl_egp < 0:
                            self._consecutive_losses += 1
                            logger.warning(
                                "⚠️ خسارة متتالية #%d/%d — %s (%.2f ج)",
                                self._consecutive_losses, self._max_consecutive_losses, sym, pnl_egp,
                            )
                        else:
                            self._consecutive_losses = 0
                        # تسجيل نتيجة الإشارة للباك تيست
                        sig_id = tr.get("signal_log_id")
                        if sig_id:
                            update_signal_result(
                                sig_id, "LOSS", pnl_egp, pnl_pct, price, "STOP",
                            )
                            update_ml_weights("LOSS", {"sym": sym})
                        tr.update({
                            "status": "closed",
                            "exit_price": price,
                            "exit_date": datetime.utcnow().isoformat(),
                            "pnl_pct": pnl_pct,
                            "pnl": pnl_egp,
                            "exit_reason": "STOP",
                        })
                        changed = True

                    elif self._mode == TRADE_MODE_SEMI:
                        self._push_signal(card)
                        mark_sent(sym, "STOP")
                        with self._pending_lock:
                            self._pending_approvals.append({
                                "type": "CLOSE_STOP",
                                "card": card,
                                "sym": sym,
                                "trade": tr,
                                "price": price,
                                "ep": ep,
                            })
                        logger.info("📋 إشارة وقف خسارة بانتظار الموافقة: %s", sym)

                    elif self._mode == TRADE_MODE_MANUAL:
                        self._push_signal(card)
                        mark_sent(sym, "STOP")

                # ────────────────────────────────────────────────────
                # فحص الأهداف القريبة
                # ────────────────────────────────────────────────────
                for i, (tgt_key, action_name, q_key) in enumerate([
                    ("near_t1", "CLOSE_T1", "q_n1_open"),
                    ("near_t2", "CLOSE_T2", "q_n2_open"),
                    ("near_t3", "CLOSE_T3", "q_n3_open"),
                ]):
                    tgt_price = tr.get(tgt_key)
                    qty_open  = tr.get(q_key, 0)
                    if (
                        tgt_price
                        and price >= tgt_price
                        and qty_open > 0
                        and not was_sent(sym, action_name)
                    ):
                        card = build_signal_card(
                            sym, v, a, t, action_name,
                            f"وصل الهدف {i + 1} = {tgt_price} ج",
                            settings,
                        )

                        if self._mode == TRADE_MODE_AUTO:
                            self._push_signal(card)
                            mark_sent(sym, action_name)
                            tr[q_key] = 0
                            # ── وقف الخسارة المتحرك: بس بعد الهدف القريب 3 يتحرك الوقف ──
                            if i == 2:
                                changed = self._apply_trailing_stop(
                                    "near_t3", sym, v, a, t, settings, tr, ep
                                ) or changed

                        elif self._mode == TRADE_MODE_SEMI:
                            self._push_signal(card)
                            mark_sent(sym, action_name)
                            with self._pending_lock:
                                self._pending_approvals.append({
                                    "type": action_name,
                                    "card": card,
                                    "sym": sym,
                                    "trade": tr,
                                    "target_idx": i,
                                    "tgt_price": tgt_price,
                                })
                            logger.info(
                                "📋 إشارة جني أرباح %d بانتظار الموافقة: %s",
                                i + 1, sym,
                            )

                        elif self._mode == TRADE_MODE_MANUAL:
                            self._push_signal(card)
                            mark_sent(sym, action_name)

                # ────────────────────────────────────────────────────
                # فحص الأهداف البعيدة
                # ────────────────────────────────────────────────────
                for i, (tgt_key, action_name, q_key) in enumerate([
                    ("far_t1", "CLOSE_FAR1", "q_f1_open"),
                    ("far_t2", "CLOSE_FAR2", "q_f2_open"),
                ]):
                    tgt_price = tr.get(tgt_key)
                    qty_open  = tr.get(q_key, 0)
                    if (
                        tgt_price
                        and price >= tgt_price
                        and qty_open > 0
                        and not was_sent(sym, action_name)
                    ):
                        card = build_signal_card(
                            sym, v, a, t, action_name,
                            f"وصل الهدف البعيد {i + 1} = {tgt_price} ج",
                            settings,
                        )

                        if self._mode == TRADE_MODE_AUTO:
                            self._push_signal(card)
                            mark_sent(sym, action_name)
                            tr[q_key] = 0
                            # ── وقف الخسارة المتحرك للأهداف البعيدة ──
                            if i == 0:  # far_t1 → حرّك الوقف لـ near_t3
                                changed = self._apply_trailing_stop(
                                    "far_t1", sym, v, a, t, settings, tr, ep
                                ) or changed
                            elif i == 1:  # far_t2 → حرّك الوقف لـ far_t1
                                changed = self._apply_trailing_stop(
                                    "far_t2", sym, v, a, t, settings, tr, ep
                                ) or changed

                        elif self._mode == TRADE_MODE_SEMI:
                            self._push_signal(card)
                            mark_sent(sym, action_name)
                            with self._pending_lock:
                                self._pending_approvals.append({
                                    "type": action_name,
                                    "card": card,
                                    "sym": sym,
                                    "trade": tr,
                                    "target_idx": i + 3,
                                    "tgt_price": tgt_price,
                                })
                            logger.info(
                                "📋 إشارة هدف بعيد %d بانتظار الموافقة: %s",
                                i + 1, sym,
                            )

                        elif self._mode == TRADE_MODE_MANUAL:
                            self._push_signal(card)
                            mark_sent(sym, action_name)

        # حفظ التغييرات
        if changed:
            save_trades(trades)

    # ══════════════════════════════════════════════════════════════
    # دوال مساعدة داخلية
    # Internal Helper Functions
    # ══════════════════════════════════════════════════════════════

    def _push_signal(self, card: Dict[str, Any]) -> Optional[int]:
        """
        إضافة إشارة للقائمة + حفظ في السجل
        Push signal to in-memory list and log to database

        المعطيات:
            card: قاموس بطاقة الإشارة

        المخرجات:
            معرف سجل الإشارة في قاعدة البيانات (للربط مع التداولات) أو None
        """
        # إضافة للقائمة في الذاكرة (الأحدث أولاً)
        with self._signals_lock:
            self._signals.insert(0, card)
            if len(self._signals) > MAX_SIGNALS_IN_MEMORY:
                self._signals.pop()

        # حفظ في قاعدة البيانات مع البيانات الموسعة
        log_result = log_signal({
            "symbol": card.get("symbol", ""),
            "action": card.get("action", ""),
            "price": card.get("price"),
            "reason": card.get("reason", ""),
            "score": card.get("score", 0.0),
            "signal_type": card.get("signal", ""),
            "entry_price": card.get("entry"),
            "stop_loss": card.get("stop"),
            "trade_quality": card.get("trade_quality"),
            "adx": card.get("adx"),
            "rsi": card.get("rsi"),
            "entry_scenario": card.get("scenario"),
            "shares": card.get("shares"),
            "card_data": json.dumps(card, ensure_ascii=False, default=str),
        })
        signal_log_id = log_result.get("db_id") if log_result else None

        # تسجيل في السجل
        logger.info(
            "  📡 إشارة جديدة: %s %s @ %s",
            card.get("action", ""), card.get("symbol", ""), card.get("price", ""),
        )

        # إشعار تليجرام (إن كان مُعدّاً)
        try:
            from notify import send_signal
            _tg = load_settings()
            send_signal(
                symbol=card.get("symbol", ""),
                action=card.get("action", ""),
                price=card.get("price", 0),
                reason=card.get("reason", ""),
                quality=card.get("trade_quality", 0),
                bot_token=_tg.get("telegram_bot_token") or None,
                chat_id=_tg.get("telegram_chat_id") or None,
            )
        except Exception:
            pass

        # استدعاء رد النداء إن وجد
        if self._on_signal_callback:
            try:
                self._on_signal_callback(card)
            except Exception as e:
                logger.error("خطأ في رد نداء الإشارة: %s", e)

        return signal_log_id

    def _open_trade(
        self,
        sym: str,
        t: Dict[str, Any],
        a: Dict[str, Any],
        v: Dict[str, Any],
        settings: Dict[str, Any],
        trades: List[Dict[str, Any]],
        open_trades: Dict[str, Dict[str, Any]],
        signal_log_id: Optional[int] = None,
        seq: int = 0,
    ) -> None:
        """
        فتح صفقة جديدة وإضافتها للقائمة
        Open a new trade and add it to the list

        المعطيات:
            sym:         رمز السهم
            t:           بيانات التداول (أهداف، وقف خسارة)
            a:           نتيجة التحليل
            v:           بيانات السهم
            settings:    إعدادات التطبيق
            trades:      قائمة التداولات (تُعدل مباشرة)
            open_trades: قاموس التداولات المفتوحة (تُعدل مباشرة)
            seq:         رقم تسلسلي للصفقة في نفس الدورة (لتفريد التوقيت)
        """
        price    = v.get("price", 0)
        cap      = settings.get("capital", DEFAULT_CAPITAL)
        risk_pct = settings.get("risk_pct", DEFAULT_RISK_PCT)

        entry_p = price  # سعر السوق الفعلي، مش entry_ideal
        near_t  = t.get("near_targets", [])
        near_p  = t.get("near_pcts", [])
        far_t   = t.get("targets", [])
        tq      = t.get("trade_quality", 0) or 0

        # override targets with ATR-based levels for realistic profit targets
        atr_val = v.get("atr")
        if atr_val and atr_val > 0 and entry_p > 0:
            sig_type = a.get("signal_type", "")
            if sig_type in ("BUY_STRONG", "BUY", "ACCUMULATE"):
                near_t = [round(entry_p + 1.0 * atr_val, 3), round(entry_p + 1.5 * atr_val, 3), round(entry_p + 2.5 * atr_val, 3)]
                far_t  = [round(entry_p + 3.5 * atr_val, 3), round(entry_p + 5.0 * atr_val, 3), round(entry_p + 7.0 * atr_val, 3)]

        rps    = abs(entry_p - t.get("stop_loss", entry_p * 0.95))
        shares = max(1, int((cap * risk_pct / 100) / rps)) if rps > 0 else 1
        q1     = int(shares * Q1_RATIO)
        q2     = int(shares * Q2_RATIO)
        q3     = shares - q1 - q2

        n1 = near_t[0] if len(near_t) > 0 else None
        n2 = near_t[1] if len(near_t) > 1 else None
        n3 = near_t[2] if len(near_t) > 2 else None
        f1 = far_t[0] if len(far_t) > 0 else None
        f2 = far_t[1] if len(far_t) > 1 else None

        # توزيع الكمية: 10% هدف قريب1، 15% قريب2، 25% قريب3، 30% بعيد1، 20% بعيد2
        q_n1 = int(shares * 0.10)
        q_n2 = int(shares * 0.15)
        q_n3 = int(shares * 0.25)
        q_f1 = int(shares * 0.30)
        q_f2 = shares - q_n1 - q_n2 - q_n3 - q_f1

        # استخدام وقت الإشارة الأصلي من السجل إن وجد
        if signal_log_id:
            from database import SignalLog as SLModel, get_session
            try:
                with get_session() as session:
                    sl = session.query(SLModel).filter(SLModel.id == signal_log_id).first()
                    signal_created = sl.created_at.isoformat() if sl and sl.created_at else None
            except Exception:
                signal_created = None
        else:
            signal_created = None

        new_trade: Dict[str, Any] = {
            "symbol":         sym,
            "entry_price":    entry_p,
            "shares":         shares,
            "q_n1_qty":       q_n1,
            "q_n2_qty":       q_n2,
            "q_n3_qty":       q_n3,
            "q_f1_qty":       q_f1,
            "q_f2_qty":       q_f2,
            "q_n1_open":      q_n1,
            "q_n2_open":      q_n2,
            "q_n3_open":      q_n3,
            "q_f1_open":      q_f1,
            "q_f2_open":      q_f2,
            "stop_loss":      t.get("stop_loss"),
            "near_t1":        n1,
            "near_t2":        n2,
            "near_t3":        n3,
            "far_t1":         f1,
            "far_t2":         f2,
            "near_targets":   [x for x in near_t if x is not None],
            "targets":        [x for x in far_t if x is not None],
            "trade_quality":  round(tq, 1),
            "signal_type":    a.get("signal_type", ""),
            "entry_scenario": t.get("entry_scenario", "WAIT"),
            "notes":          {"text": f"تلقائي — {a.get('signal', '')} — جودة {round(tq, 0)}"},
            "status":         "active",
            "auto":           True,
            "signal_log_id":  signal_log_id,
            "entry_date":     signal_created or (cairo_now() + timedelta(seconds=seq)).isoformat(),
            "exit_date":      None,
            "exit_price":     None,
            "pnl_pct":        None,
            "pnl":            None,
            "exit_reason":    None,
        }

        # إضافة الصفقة
        try:
            result = add_trade(new_trade)
            # تحديث قاموس التداولات المفتوحة ببيانات الصفقة الحقيقية من قاعدة البيانات
            if result:
                new_trade.update(result)
            trades.append(new_trade)
            open_trades[sym] = new_trade
            logger.info(
                "🚀 تم فتح صفقة: %s — الدخول: %.2f، الكمية: %d سهم",
                sym, entry_p, shares,
            )
        except Exception as e:
            logger.error("خطأ في فتح الصفقة %s: %s", sym, e)
            # إضافة محلية كاحتياط
            trades.append(new_trade)
            open_trades[sym] = new_trade

    def _apply_trailing_stop(
        self,
        trigger: str,
        sym: str,
        v: Dict[str, Any],
        a: Dict[str, Any],
        t: Dict[str, Any],
        settings: Dict[str, Any],
        tr: Dict[str, Any],
        entry_price: float,
    ) -> bool:
        """
        تطبيق وقف الخسارة المتحرك بعد بلوغ كل هدف
        Apply trailing stop after each target is hit

        القواعد:
        - near_t3:  حرّك الوقف لسعر الدخول (صفقة بلا خسارة)
        - far_t1:   حرّك الوقف لـ near_t3
        - far_t2:   حرّك الوقف لـ far_t1

        المعطيات:
            trigger:     المحفز (near_t3, far_t1, far_t2)
            sym:         رمز السهم
            v:           بيانات السهم
            a:           نتيجة التحليل
            t:           بيانات التداول
            settings:    إعدادات التطبيق
            tr:          بيانات الصفقة (تُعدل مباشرة)
            entry_price: سعر الدخول

        المخرجات:
            True إذا تم تعديل الصفقة، False خلاف ذلك
        """
        changed = False
        price = v.get("price", 0)

        if trigger == "near_t3":
            # بعد الهدف القريب 3 → الوقف لسعر الدخول (صفقة بلا خسارة)
            self._consecutive_losses = 0
            new_sl = round(entry_price * 1.001, 3)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (سعر الدخول)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

        elif trigger == "far_t1":
            # بعد الهدف البعيد 1 → الوقف لـ near_t3
            new_sl = tr.get("near_t3", entry_price)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (الهدف القريب 3)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

        elif trigger == "far_t2":
            # بعد الهدف البعيد 2 → الوقف لـ far_t1
            new_sl = tr.get("far_t1", entry_price)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (الهدف البعيد 1)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

            # لو خلصت كل الكمية → غلق الصفقة
            total_open = sum(tr.get(k, 0) for k in ("q_n1_open", "q_n2_open", "q_n3_open", "q_f1_open", "q_f2_open"))
            if total_open == 0:
                pnl_pct = round((price - entry_price) / entry_price * 100, 2) if entry_price else 0
                pnl_egp = round((price - entry_price) * tr.get("q_f2_qty", 0), 2) if entry_price else 0
                # خصم مصاريف التداول (افتراضي 0.6% جولة كاملة)
                comm = _calc_commission(entry_price, price, tr.get("q_f2_qty", 0), settings)
                pnl_egp -= comm
                self._daily_pnl += pnl_egp
                self._consecutive_losses = 0
                sig_id = tr.get("signal_log_id")
                if sig_id:
                    update_signal_result(
                        sig_id, "WIN",
                        pnl_egp, pnl_pct, price, "TARGETS",
                    )
                    update_ml_weights("WIN", {"sym": sym})
                tr.update({
                    "status": "closed",
                    "exit_price": price,
                    "exit_date": datetime.utcnow().isoformat(),
                    "pnl_pct": pnl_pct,
                    "pnl": pnl_egp,
                    "exit_reason": "TARGETS",
                })
                changed = True

        return changed

    def _reset_daily_pnl_if_new_day(self) -> None:
        """
        إعادة تعيين الخسارة اليومية إذا بدأ يوم جديد
        Reset daily P&L if a new day has started
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._daily_pnl_date:
            if self._daily_pnl_date:
                logger.info(
                    "📊 خلاصة اليوم %s: %.2f ج | خسائر متتالية: %d",
                    self._daily_pnl_date, self._daily_pnl, self._consecutive_losses,
                )
            self._daily_pnl = 0.0
            self._daily_pnl_date = today
            self._consecutive_losses = 0
            logger.info("🔄 تم إعادة تعيين الخسارة اليومية ليوم %s", today)

    # ══════════════════════════════════════════════════════════════
    # دوال الموافقة (لوضع SEMI_AUTO)
    # Approval Functions (for SEMI_AUTO mode)
    # ══════════════════════════════════════════════════════════════

    def approve_pending(self, approval_id: int = 0) -> bool:
        """
        الموافقة على إشارة معلقة (في وضع SEMI_AUTO)

        المعطيات:
            approval_id: فهرس الإشارة المعلقة (الافتراضي: 0 = الأقدم)

        المخرجات:
            True إذا تمت الموافقة بنجاح، False خلاف ذلك
        """
        with self._pending_lock:
            if not self._pending_approvals or approval_id >= len(self._pending_approvals):
                logger.warning("لا توجد إشارة معلقة بالفهرس %d", approval_id)
                return False

            pending = self._pending_approvals.pop(approval_id)

        pending_type = pending.get("type")
        logger.info("✅ تمت الموافقة على إشارة: %s %s", pending_type, pending.get("sym", ""))

        # تنفيذ الإشارة حسب نوعها
        if pending_type == "OPEN":
            sym = pending["sym"]
            t   = pending["t"]
            a   = pending["a"]
            v   = pending["v"]
            settings = pending["settings"]

            trades = load_trades()
            open_trades = {tr["symbol"]: tr for tr in trades if tr.get("status") == "active"}
            self._open_trade(sym, t, a, v, settings, trades, open_trades)
            save_trades(trades)

        elif pending_type == "CLOSE_STOP":
            sym   = pending["sym"]
            tr    = pending["trade"]
            price = pending["price"]
            ep    = pending["ep"]

            pnl_pct = round((price - ep) / ep * 100, 2) if ep else 0
            pnl_egp = round((price - ep) * tr.get("shares", 0), 2) if ep else 0
            comm = _calc_commission(ep, price, tr.get("shares", 0), load_settings())
            pnl_egp -= comm
            self._daily_pnl += pnl_egp
            tr.update({
                "status": "closed",
                "exit_price": price,
                "exit_date": datetime.utcnow().isoformat(),
                "pnl_pct": pnl_pct,
                "pnl": pnl_egp,
                "exit_reason": "STOP",
            })
            # حفظ التغييرات
            trades = load_trades()
            for i, existing in enumerate(trades):
                if existing.get("symbol") == sym and existing.get("status") == "active":
                    trades[i] = tr
                    break
            save_trades(trades)

        elif pending_type in ("CLOSE_T1", "CLOSE_T2", "CLOSE_T3", "CLOSE_FAR1", "CLOSE_FAR2"):
            sym        = pending["sym"]
            tr         = pending["trade"]
            target_idx = pending["target_idx"]

            # تحديث الكمية المتبقية
            q_keys = ["q_n1_open", "q_n2_open", "q_n3_open", "q_f1_open", "q_f2_open"]
            if target_idx < len(q_keys):
                tr[q_keys[target_idx]] = 0

            # تطبيق وقف الخسارة المتحرك
            trades = load_trades()
            v = pending.get("card", {})
            trigger_map = {2: "near_t3", 3: "far_t1", 4: "far_t2"}
            trigger = trigger_map.get(target_idx)
            if trigger:
                self._apply_trailing_stop(
                    trigger, sym, v, {}, {},
                    load_settings(), tr, tr.get("entry_price", 0),
                )
            # حفظ التغييرات
            for i, existing in enumerate(trades):
                if existing.get("symbol") == sym and existing.get("status") == "active":
                    trades[i] = tr
                    break
            save_trades(trades)

        return True

    def reject_pending(self, approval_id: int = 0) -> bool:
        """
        رفض إشارة معلقة (في وضع SEMI_AUTO)

        المعطيات:
            approval_id: فهرس الإشارة المعلقة (الافتراضي: 0 = الأقدم)

        المخرجات:
            True إذا تم الرفض بنجاح، False خلاف ذلك
        """
        with self._pending_lock:
            if not self._pending_approvals or approval_id >= len(self._pending_approvals):
                logger.warning("لا توجد إشارة معلقة بالفهرس %d", approval_id)
                return False

            pending = self._pending_approvals.pop(approval_id)
            logger.info(
                "❌ تم رفض إشارة: %s %s",
                pending.get("type", ""), pending.get("sym", ""),
            )
            return True

    def clear_pending(self) -> int:
        """
        مسح جميع الإشارات المعلقة

        المخرجات:
            عدد الإشارات التي تم مسحها
        """
        with self._pending_lock:
            count = len(self._pending_approvals)
            self._pending_approvals.clear()
        logger.info("🗑️ تم مسح %d إشارة معلقة", count)
        return count

    # ══════════════════════════════════════════════════════════════
    # دوال الحالة والتشخيص
    # Status and Diagnostics Functions
    # ══════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """
        الحصول على حالة محرك القرار الحالية

        المخرجات:
            قاموس يحتوي على:
            - is_running: هل المحرك يعمل
            - mode: وضع التداول
            - interval: الفترة الزمنية
            - daily_pnl: الربح/الخسارة اليومي
            - daily_loss_limit: حد الخسارة اليومي
            - signals_count: عدد الإشارات في الذاكرة
            - pending_count: عدد الإشارات المعلقة
            - daily_pnl_date: تاريخ الربح/الخسارة اليومي
        """
        return {
            "is_running": self.is_running,
            "mode": self._mode,
            "interval": self._interval,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_loss_limit": self._daily_loss_limit,
            "daily_limit_egp": round(
                load_settings().get("capital", DEFAULT_CAPITAL) * self._daily_loss_limit / 100, 2
            ),
            "signals_count": len(self._signals),
            "pending_count": len(self._pending_approvals),
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self._max_consecutive_losses,
            "daily_pnl_date": self._daily_pnl_date,
        }

    def get_recent_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        الحصول على أحدث الإشارات من الذاكرة

        المعطيات:
            limit: الحد الأقصى لعدد الإشارات (الافتراضي: 20)

        المخرجات:
            قائمة بأحدث الإشارات
        """
        with self._signals_lock:
            return list(self._signals[:limit])


# ══════════════════════════════════════════════════════════════════════════════
# كشف الصرف الجماعي في السوق
# Market Distribution / Dump Detection
# ══════════════════════════════════════════════════════════════════════════════

def detect_market_distribution(stocks: Dict[str, Any]) -> Dict[str, Any]:
    """
    كشف حالة السوق: صرف جماعي / تجميع / عادي
    - Market Breadth (نسبة الأسهم الصاعدة/الهابطة)
    - الأسهم فوق/تحت سعر الفتح
    - حجم مرتفع مع نزول (صرف) أو صعود (تجميع)
    - الأسهم قرب أدنى/أعلى اليوم
    """
    total = len(stocks)
    if total == 0:
        return {"distribution": False, "accumulation": False, "severity": 0, "advancing_pct": 50}

    advancing = 0
    declining = 0
    below_open = 0
    above_open = 0
    volume_surge_red = 0
    volume_surge_green = 0
    near_day_low = 0
    near_day_high = 0

    for sym, v in stocks.items():
        # v is StockData object, convert to dict lookup
        vd = v if isinstance(v, dict) else vars(v)
        price = vd.get("price", 0)
        chg = vd.get("change_pct", 0) or 0

        if chg > 0:
            advancing += 1
        elif chg < 0:
            declining += 1

        chg_from_open = vd.get("chg_from_open", 0) or 0
        if chg_from_open < -1:
            below_open += 1
        elif chg_from_open > 1:
            above_open += 1

        rel_vol = (vd.get("volume", 0) / vd.get("avg_vol", 1)) if (vd.get("avg_vol") or 0) > 0 else 0
        if rel_vol > 1.5 and chg < -1:
            volume_surge_red += 1
        elif rel_vol > 1.5 and chg > 1:
            volume_surge_green += 1

        day_high = vd.get("day_high", 0)
        day_low = vd.get("day_low", 0)
        if day_high and day_low and price and (day_high - day_low) > 0:
            pos_in_range = (price - day_low) / (day_high - day_low)
            if pos_in_range < 0.3 and chg < 0:
                near_day_low += 1
            elif pos_in_range > 0.7 and chg > 0:
                near_day_high += 1

    advancing_pct = advancing / total * 100
    declining_pct = declining / total * 100
    below_open_pct = below_open / total * 100
    above_open_pct = above_open / total * 100
    surge_red_pct = volume_surge_red / total * 100
    surge_green_pct = volume_surge_green / total * 100
    near_low_pct = near_day_low / total * 100
    near_high_pct = near_day_high / total * 100

    # — صرف جماعي —
    dist_severity = 0
    dist_warnings = []

    if advancing_pct < 25:
        dist_severity += 4
        dist_warnings.append("أقل من 25% من الأسهم صاعدة — صرف جماعي شديد")
    elif advancing_pct < 35:
        dist_severity += 3
        dist_warnings.append(f"أقل من 35% من الأسهم صاعدة ({advancing_pct:.0f}%)")
    elif advancing_pct < 45:
        dist_severity += 2
        dist_warnings.append(f"نسبة الأسهم الصاعدة منخفضة ({advancing_pct:.0f}%)")
    elif advancing_pct < 55:
        dist_severity += 1

    if below_open_pct > 60:
        dist_severity += 3
        dist_warnings.append(f"أكثر من 60% من الأسهم تحت سعر الفتح ({below_open_pct:.0f}%)")
    elif below_open_pct > 40:
        dist_severity += 1

    if surge_red_pct > 15:
        dist_severity += 2
        dist_warnings.append(f"{surge_red_pct:.0f}% من الأسهم تنزل بحجم مرتفع")
    elif surge_red_pct > 8:
        dist_severity += 1

    if near_low_pct > 30:
        dist_severity += 2
        dist_warnings.append(f"{near_low_pct:.0f}% من الأسهم قرب أدنى اليوم")
    elif near_low_pct > 20:
        dist_severity += 1

    distribution = dist_severity >= 3
    dist_severity = min(dist_severity, 5)

    # — تجميع سوقي —
    acc_severity = 0
    acc_warnings = []

    if advancing_pct > 75:
        acc_severity += 4
        acc_warnings.append(f"أكثر من 75% من الأسهم صاعدة — تجميع سوقي قوي")
    elif advancing_pct > 65:
        acc_severity += 3
        acc_warnings.append(f"أكثر من 65% من الأسهم صاعدة ({advancing_pct:.0f}%)")
    elif advancing_pct > 55:
        acc_severity += 2
        acc_warnings.append(f"نسبة الأسهم الصاعدة مرتفعة ({advancing_pct:.0f}%)")
    elif advancing_pct > 45:
        acc_severity += 1

    if above_open_pct > 50:
        acc_severity += 2
        acc_warnings.append(f"{above_open_pct:.0f}% من الأسهم فوق سعر الفتح")
    elif above_open_pct > 35:
        acc_severity += 1

    if surge_green_pct > 15:
        acc_severity += 2
        acc_warnings.append(f"{surge_green_pct:.0f}% من الأسهم تصعد بحجم مرتفع")
    elif surge_green_pct > 8:
        acc_severity += 1

    if near_high_pct > 25:
        acc_severity += 2
        acc_warnings.append(f"{near_high_pct:.0f}% من الأسهم قرب أعلى اليوم")
    elif near_high_pct > 15:
        acc_severity += 1

    accumulation = acc_severity >= 3 and acc_severity > dist_severity
    acc_severity = min(acc_severity, 5)

    # تحديد الحالة النهائية
    if accumulation:
        state = "تجميع"
        severity = acc_severity
        warnings = acc_warnings
    elif distribution:
        state = "صرف"
        severity = dist_severity
        warnings = dist_warnings
    else:
        state = "عادي"
        severity = 0
        warnings = []

    names = {0: "عادي", 1: "خفيف", 2: "متوسط", 3: "قوي", 4: "قوي جداً", 5: "شديد"}
    return {
        "state": state,
        "distribution": distribution,
        "accumulation": accumulation,
        "severity": severity,
        "level": names.get(severity, "غير معروف"),
        "advancing_pct": round(advancing_pct, 1),
        "declining_pct": round(declining_pct, 1),
        "below_open_pct": round(below_open_pct, 1),
        "above_open_pct": round(above_open_pct, 1),
        "volume_surge_red_pct": round(surge_red_pct, 1),
        "volume_surge_green_pct": round(surge_green_pct, 1),
        "near_day_low_pct": round(near_low_pct, 1),
        "near_day_high_pct": round(near_high_pct, 1),
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HTML Frontend (embedded) - الواجهة الأمامية
# ══════════════════════════════════════════════════════════════════════════════

_EMBEDDED_HTML = """<!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><title>EGX Analyzer</title></head><body style="background:#0a0e1a;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh"><h2>⚠️ index.html غير موجود</h2></body></html>"""

def _get_html_frontend() -> str:
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    try:
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        logger.warning(f"فشل تحميل index.html: {e}")
    return _EMBEDDED_HTML
