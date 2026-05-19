import sys, os, json, logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# ── constants ──
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
DATABASE_URL = os.getenv("DATABASE_URL", "")

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
\u26a0\ufe0f \u062a\u0646\u0648\u064a\u0647 \u0645\u062e\u0627\u0637\u0631 \u0645\u0647\u0645
"""

TRADE_MODE_AUTO = "auto"

# ── Base ──
Base = declarative_base()

# ── DB globals ──
_engine = None
_SessionFactory = None

# ── DB code ──
def _get_engine():
    """
    الحصول على محرك قاعدة البيانات - إنشاء واحد فقط (Singleton)
    Get the database engine - create only one (Singleton)
    """
    global _engine
    if _engine is None:
        if DATABASE_URL:
            # PostgreSQL (أو أي URL مباشر)
            _engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
            logger.info(f"تم إنشاء محرك قاعدة البيانات من DATABASE_URL")
        else:
            # SQLite محلي
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"تم إنشاء مجلد قاعدة البيانات: {db_dir}")
            _engine = create_engine(
                f"sqlite:///{DB_PATH}",
                echo=False,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
            logger.info(f"تم إنشاء محرك قاعدة البيانات: {DB_PATH}")
    return _engine


def _get_session_factory():
    """
    الحصول على مصنع الجلسات - إنشاء واحد فقط (Singleton)
    Get the session factory - create only one (Singleton)
    """
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=_get_engine(),
            autocommit=False,
            autoflush=False,
        )
        logger.info("تم إنشاء مصنع جلسات قاعدة البيانات")
    return _SessionFactory


# =============================================================================
# نماذج قاعدة البيانات (ORM Models)
# Database Models
# =============================================================================

class Setting(Base):
    """
    نموذج الإعدادات - تخزين القيم الأساسية للتطبيق
    Settings model - key/value store for app settings

    يُستخدم لتخزين إعدادات التطبيق في شكل مفتاح/قيمة.
    يمكن تشفير القيم الحساسة مثل مفاتيح API.
    """
    __tablename__ = "settings"

    # المفتاح الأساسي
    id = Column(Integer, primary_key=True, autoincrement=True)
    # مفتاح الإعداد - فريد
    key = Column(String(255), unique=True, nullable=False, index=True)
    # قيمة الإعداد - نصية لدعم أنواع مختلفة
    value = Column(Text, nullable=True)
    # هل القيمة مشفرة
    encrypted = Column(Boolean, default=False, nullable=False)
    # تاريخ آخر تحديث
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """تحويل النموذج إلى قاموس"""
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "encrypted": self.encrypted,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Trade(Base):
    """
    نموذج التداول - تتبع الصفقات
    Trade model - trade tracking

    يُستخدم لتتبع الصفقات النشطة والمغلقة مع تفاصيل الدخول والخروج
    والأهداف المتعددة (Q1, Q2, Q3) ووقف الخسارة.
    """
    __tablename__ = "trades"

    # المفتاح الأساسي
    id = Column(Integer, primary_key=True, autoincrement=True)
    # رمز السهم
    symbol = Column(String(50), nullable=False, index=True)
    # سعر الدخول
    entry_price = Column(Float, nullable=False)
    # عدد الأسهم
    shares = Column(Integer, nullable=False, default=0)
    # رابط الإشارة المسببة (للباك تيست)
    signal_log_id = Column(Integer, nullable=True)
    # كمية الربع الأول
    q1_qty = Column(Integer, nullable=True, default=0)
    # كمية الربع الثاني
    q2_qty = Column(Integer, nullable=True, default=0)
    # كمية الربع الثالث
    q3_qty = Column(Integer, nullable=True, default=0)
    # كميات الأهداف الجديدة (قريب/بعيد)
    q_n1_qty = Column(Integer, nullable=True, default=0)
    q_n2_qty = Column(Integer, nullable=True, default=0)
    q_n3_qty = Column(Integer, nullable=True, default=0)
    q_f1_qty = Column(Integer, nullable=True, default=0)
    q_f2_qty = Column(Integer, nullable=True, default=0)
    q_n1_open = Column(Integer, nullable=True, default=0)
    q_n2_open = Column(Integer, nullable=True, default=0)
    q_n3_open = Column(Integer, nullable=True, default=0)
    q_f1_open = Column(Integer, nullable=True, default=0)
    q_f2_open = Column(Integer, nullable=True, default=0)
    # وقف الخسارة
    stop_loss = Column(Float, nullable=True)
    # الأهداف - مخزنة كنص JSON
    targets = Column(Text, nullable=True)
    near_targets = Column(Text, nullable=True)
    # حالة الصفقة: active, closed, cancelled
    status = Column(String(20), nullable=False, default="active", index=True)
    # الربح/الخسارة
    pnl = Column(Float, nullable=True, default=0.0)
    # نسبة الربح/الخسارة
    pnl_pct = Column(Float, nullable=True, default=0.0)
    # سعر الخروج
    exit_price = Column(Float, nullable=True)
    # سبب الخروج
    exit_reason = Column(String(255), nullable=True)
    # تاريخ الدخول
    entry_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    # تاريخ الخروج
    exit_date = Column(DateTime, nullable=True)
    # ملاحظات إضافية - مخزنة كنص JSON
    notes = Column(Text, nullable=True)
    # تاريخ الإنشاء
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # تاريخ التحديث
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """تحويل النموذج إلى قاموس"""
        targets_raw = self.targets
        notes_raw = self.notes
        near_raw = self.near_targets
        return {
            "id": self.id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "shares": self.shares,
            "signal_log_id": self.signal_log_id,
            "q1_qty": self.q1_qty,
            "q2_qty": self.q2_qty,
            "q3_qty": self.q3_qty,
            "q_n1_qty": self.q_n1_qty,
            "q_n2_qty": self.q_n2_qty,
            "q_n3_qty": self.q_n3_qty,
            "q_f1_qty": self.q_f1_qty,
            "q_f2_qty": self.q_f2_qty,
            "q_n1_open": self.q_n1_open,
            "q_n2_open": self.q_n2_open,
            "q_n3_open": self.q_n3_open,
            "q_f1_open": self.q_f1_open,
            "q_f2_open": self.q_f2_open,
            "stop_loss": self.stop_loss,
            "targets": json.loads(targets_raw) if targets_raw else [],
            "near_targets": json.loads(near_raw) if near_raw else [],
            "status": self.status,
            "pnl": self.pnl,
            "pnl_egp": self.pnl,
            "pnl_pct": self.pnl_pct,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "notes": json.loads(notes_raw) if notes_raw else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SignalLog(Base):
    """
    نموذج سجل الإشارات - تسجيل الإشارات المكتشفة
    Signal log model - logged signals

    يُستخدم لتسجيل جميع الإشارات التي يكتشفها المحلل الإحصائي
    مع تفاصيل السبب والنتيجة والتقييم.
    """
    __tablename__ = "signals_log"

    # المفتاح الأساسي
    id = Column(Integer, primary_key=True, autoincrement=True)
    # رمز السهم
    symbol = Column(String(50), nullable=False, index=True)
    # نوع الإجراء: OPEN, CLOSE_T1, CLOSE_T2, CLOSE_T3, CLOSE_STOP, TRAIL_STOP
    action = Column(String(20), nullable=False)
    # سعر الإشارة
    price = Column(Float, nullable=True)
    # سبب الإشارة
    reason = Column(Text, nullable=True)
    # درجة الإشارة (0-100)
    score = Column(Float, nullable=True, default=0.0)
    # نوع الإشارة: breakout, reversal, momentum, support, resistance
    signal_type = Column(String(50), nullable=True, index=True)
    # --- الحقول الموسعة للباك تيست ---
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    trade_quality = Column(Float, nullable=True)
    adx = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    entry_scenario = Column(String(20), nullable=True)
    shares = Column(Integer, nullable=True)
    result = Column(String(10), nullable=True)  # WIN / LOSS / null
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    exit_date = Column(DateTime, nullable=True)
    # --- الحقول الموسعة للبطاقة الكاملة ---
    card_data = Column(Text, nullable=True)  # JSON كامل لبطاقة الإشارة
    # --- نهاية الحقول الموسعة ---
    # تاريخ الإنشاء
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """تحويل النموذج إلى قاموس"""
        import json as _json
        card = {}
        if self.card_data:
            try:
                card = _json.loads(self.card_data)
            except Exception:
                pass
        return {
            "id": self.id,
            "symbol": self.symbol,
            "action": self.action,
            "price": self.price,
            "reason": self.reason,
            "score": self.score,
            "signal_type": self.signal_type,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "trade_quality": self.trade_quality,
            "adx": self.adx,
            "rsi": self.rsi,
            "entry_scenario": self.entry_scenario,
            "shares": self.shares,
            "result": self.result,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            **card,
        }


class SentSignal(Base):
    """
    نموذج الإشارات المُرسلة - منع التكرار
    Sent signal model - dedup tracking

    يُستخدم لتتبع الإشارات التي تم إرسالها بالفعل لمنع
    إرسال نفس الإشارة أكثر من مرة في نفس اليوم.
    """
    __tablename__ = "sent_signals"

    # المفتاح الأساسي
    id = Column(Integer, primary_key=True, autoincrement=True)
    # رمز السهم
    symbol = Column(String(50), nullable=False, index=True)
    # نوع الإشارة
    signal_type = Column(String(50), nullable=False, index=True)
    # تاريخ الإرسال
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """تحويل النموذج إلى قاموس"""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class User(Base):
    """نموذج المستخدمين للتسجيل والدخول"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin / user
    plan = Column(String(20), nullable=False, default="free")  # free / premium
    premium_until = Column(DateTime, nullable=True)
    email_confirmed = Column(Boolean, default=False, nullable=False)
    confirmation_token = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "plan": self.plan,
            "premium_until": self.premium_until.isoformat() if self.premium_until else None,
            "email_confirmed": self.email_confirmed,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PremiumCode(Base):
    """نموذج أكواد الاشتراك المميز"""
    __tablename__ = "premium_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    duration_days = Column(Integer, nullable=False, default=30)
    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_by = Column(String(500), nullable=True)  # comma-separated usernames

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "duration_days": self.duration_days,
            "max_uses": self.max_uses,
            "used_count": self.used_count,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "used_by": self.used_by,
        }


class Visit(Base):
    """نموذج زيارات الموقع للتتبع والإحصائيات"""
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(45), nullable=False, index=True)
    user_agent = Column(String(500), nullable=True)
    page = Column(String(255), nullable=True, default="/")
    visited_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "page": self.page,
            "visited_at": self.visited_at.isoformat() if self.visited_at else None,
        }


# =============================================================================
# تهيئة قاعدة البيانات
# Database initialization
# =============================================================================

def init_db() -> None:
    """
    تهيئة قاعدة البيانات - إنشاء الجداول إذا لم تكن موجودة
    Initialize database - create tables if they don't exist

    تقوم هذه الدالة بإنشاء جميع الجداول المعرّفة في النماذج
    إذا لم تكن موجودة بالفعل. تُستدعى مرة واحدة عند بدء التطبيق.
    """
    try:
        engine = _get_engine()
        # WAL mode for concurrent reads
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=5000"))
            conn.commit()
        Base.metadata.create_all(bind=engine)
        logger.info("تم تهيئة قاعدة البيانات بنجاح - جميع الجداول جاهزة")
        _migrate_db(engine)  # ترحيل الأعمدة الجديدة
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تهيئة قاعدة البيانات: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تهيئة قاعدة البيانات: {e}")
        raise


def _migrate_db(engine) -> None:
    """
    ترحيل قاعدة البيانات - إضافة أعمدة جديدة للجداول الموجودة
    Database migration - add new columns to existing tables

    SQLite لا يدعم ALTER TABLE ADD COLUMN مع قيود NOT NULL
    لذا كل الأعمدة الجديدة nullable.
    """
    new_columns = {
        "signals_log": [
            "entry_price Float",
            "stop_loss Float",
            "trade_quality Float",
            "adx Float",
            "rsi Float",
            "entry_scenario VARCHAR(20)",
            "shares INTEGER",
            "result VARCHAR(10)",
            "pnl Float",
            "pnl_pct Float",
            "exit_price Float",
            "exit_reason VARCHAR(50)",
            "exit_date DATETIME",
            "card_data TEXT",
        ],
        "trades": [
            "signal_log_id INTEGER",
            "near_targets TEXT",
        ],
        "users": [
            "plan VARCHAR(20) DEFAULT 'free'",
            "premium_until DATETIME",
            "email_confirmed BOOLEAN DEFAULT 0",
            "confirmation_token VARCHAR(255)",
        ],
    }
    for table, columns in new_columns.items():
        for col_def in columns:
            col_name = col_def.split()[0]
            try:
                engine.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                logger.info(f"تم إضافة عمود {col_name} إلى جدول {table}")
            except Exception:
                pass  # العمود موجود مسبقاً
    # إنشاء جدول premium_codes لو مش موجود
    try:
        PremiumCode.__table__.create(engine, checkfirst=True)
        logger.info("تم التأكد من وجود جدول premium_codes")
    except Exception:
        pass


# =============================================================================
# إدارة الجلسات - آمنة للخيوط المتعددة
# Session management - thread-safe
# =============================================================================

@contextmanager
def get_session():
    """
    مدير سياق للحصول على جلسة قاعدة البيانات - آمن للخيوط المتعددة
    Context manager for database sessions - thread-safe

    الاستخدام:
        with get_session() as session:
            result = session.query(Model).all()

    يتم التأكد من إغلاق الجلسة تلقائياً بعد الانتهاء.
    في حالة حدوث خطأ، يتم التراجع عن التغييرات.
    """
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"خطأ في جلسة قاعدة البيانات - تم التراجع: {e}")
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"خطأ غير متوقع في جلسة قاعدة البيانات: {e}")
        raise
    finally:
        session.close()


# =============================================================================
# عمليات الإعدادات
# Settings operations
# =============================================================================

def load_settings() -> Dict[str, Any]:
    """
    تحميل جميع الإعدادات كقاموس
    Load all settings as a dictionary

    Returns:
        قاموس يحتوي على جميع الإعدادات حيث المفتاح هو اسم الإعداد
        والقيمة هي قيمة الإعداد. القيم المشفرة تُرجع كما هي (نص).
    """
    try:
        with get_session() as session:
            settings = session.query(Setting).all()
            result = {}
            for s in settings:
                # محاولة تحليل القيم JSON إذا أمكن
                value = s.value
                if value is not None:
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        pass  # الاحتفاظ بالقيمة كنص عادي
                result[s.key] = value
            logger.debug(f"تم تحميل {len(result)} إعداد")
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تحميل الإعدادات: {e}")
        return {}
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تحميل الإعدادات: {e}")
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """
    حفظ الإعدادات - دمج مع الإعدادات الموجودة
    Save settings - merge with existing settings

    Args:
        settings: قاموس الإعدادات للحفظ. يتم دمج القيم الجديدة
                  مع الإعدادات الموجودة دون حذف الإعدادات الأخرى.

    القيم غير النصية يتم تحويلها تلقائياً إلى JSON للتخزين.
    """
    if not settings:
        return

    try:
        with get_session() as session:
            for key, value in settings.items():
                # تحويل القيمة إلى نص للتخزين
                if value is None:
                    str_value = None
                elif isinstance(value, (dict, list, bool)):
                    str_value = json.dumps(value, ensure_ascii=False)
                else:
                    str_value = str(value)

                # البحث عن إعداد موجود
                existing = session.query(Setting).filter(Setting.key == key).first()
                if existing:
                    existing.value = str_value
                    existing.updated_at = datetime.utcnow()
                else:
                    # إنشاء إعداد جديد
                    new_setting = Setting(
                        key=key,
                        value=str_value,
                        encrypted=False,
                        updated_at=datetime.utcnow(),
                    )
                    session.add(new_setting)

            logger.info(f"تم حفظ {len(settings)} إعداد")
    except SQLAlchemyError as e:
        logger.error(f"خطأ في حفظ الإعدادات: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في حفظ الإعدادات: {e}")
        raise


# =============================================================================
# عمليات التداولات
# Trades operations
# =============================================================================

def _dict_to_trade(data: Dict[str, Any]) -> Trade:
    """تحويل قاموس بيانات تداول إلى كائن Trade"""
    # backward compatibility: تقبل individual fields (near_t1, target1, …) لو targets arrays مش موجودة
    raw_targets = data.get("targets")
    if not raw_targets:
        raw_targets = [t for t in [data.get("target1"), data.get("target2"), data.get("target3")] if t is not None]
    raw_near = data.get("near_targets")
    if not raw_near:
        raw_near = [t for t in [data.get("near_t1"), data.get("near_t2"), data.get("near_t3")] if t is not None]
    return Trade(
        symbol=data.get("symbol", ""),
        entry_price=data.get("entry_price", 0.0),
        shares=data.get("shares", 1),
        signal_log_id=data.get("signal_log_id"),
        q1_qty=data.get("q1_qty", 0),
        q2_qty=data.get("q2_qty", 0),
        q3_qty=data.get("q3_qty", 0),
        q_n1_qty=data.get("q_n1_qty", data.get("q1_qty", 0)),
        q_n2_qty=data.get("q_n2_qty", data.get("q2_qty", 0)),
        q_n3_qty=data.get("q_n3_qty", data.get("q3_qty", 0)),
        q_f1_qty=data.get("q_f1_qty", 0),
        q_f2_qty=data.get("q_f2_qty", 0),
        q_n1_open=data.get("q_n1_open", data.get("q1_qty", 0)),
        q_n2_open=data.get("q_n2_open", data.get("q2_qty", 0)),
        q_n3_open=data.get("q_n3_open", data.get("q3_qty", 0)),
        q_f1_open=data.get("q_f1_open", 0),
        q_f2_open=data.get("q_f2_open", 0),
        stop_loss=data.get("stop_loss"),
        targets=json.dumps(raw_targets) if raw_targets else None,
        near_targets=json.dumps(raw_near) if raw_near else None,
        status=data.get("status", "active"),
        pnl=data.get("pnl", 0.0),
        pnl_pct=data.get("pnl_pct", 0.0),
        exit_price=data.get("exit_price"),
        exit_reason=data.get("exit_reason"),
        notes=json.dumps(data.get("notes", {})) if data.get("notes") else None,
    )


def load_trades() -> List[Dict[str, Any]]:
    """
    تحميل جميع التداولات
    Load all trades

    Returns:
        قائمة بجميع التداولات مرتبة بتاريخ الإنشاء (الأحدث أولاً)
        كل تداول يتم تحويله إلى قاموس.
    """
    try:
        with get_session() as session:
            trades = session.query(Trade).order_by(Trade.created_at.desc()).all()
            result = [t.to_dict() for t in trades]
            logger.debug(f"تم تحميل {len(result)} تداول")
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تحميل التداولات: {e}")
        return []
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تحميل التداولات: {e}")
        return []


def save_trades(trades: List[Dict[str, Any]]) -> None:
    """
    حفظ التداولات - استبدال جميع التداولات الموجودة
    Save trades - replace all existing trades

    Args:
        trades: قائمة التداولات الجديدة. يتم حذف جميع التداولات
                الموجودة واستبدالها بهذه القائمة.

    تحذير: هذه العملية تحذف جميع التداولات السابقة!
    """
    if trades is None:
        return

    try:
        with get_session() as session:
            # حذف جميع التداولات الموجودة
            session.query(Trade).delete()

            # إضافة التداولات الجديدة
            for trade_data in trades:
                trade = _dict_to_trade(trade_data)
                session.add(trade)

            logger.info(f"تم حفظ {len(trades)} تداول (استبدال كامل)")
    except SQLAlchemyError as e:
        logger.error(f"خطأ في حفظ التداولات: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في حفظ التداولات: {e}")
        raise


def add_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    """
    إضافة تداول جديد
    Add a single trade

    Args:
        trade: قاموس بيانات التداول الجديد

    Returns:
        قاموس التداول المُضاف مع المعرف الجديد

    الحقول المطلوبة كحد أدنى: symbol, entry_price, shares
    """
    if not trade or not trade.get("symbol"):
        raise ValueError("يجب توفير رمز السهم على الأقل")

    try:
        with get_session() as session:
            new_trade = _dict_to_trade(trade)
            session.add(new_trade)
            session.flush()  # للحصول على المعرف الجديد
            result = new_trade.to_dict()
            logger.info(f"تم إضافة تداول جديد: {trade['symbol']} - معرف: {new_trade.id}")
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في إضافة تداول: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في إضافة تداول: {e}")
        raise


def close_trade(trade_id: int, exit_price: float, reason: str = "") -> Optional[Dict[str, Any]]:
    """
    إغلاق تداول محدد
    Close a specific trade

    Args:
        trade_id: معرف التداول المراد إغلاقه
        exit_price: سعر الخروج
        reason: سبب الإغلاق

    Returns:
        قاموس التداول المُغلق أو None إذا لم يتم العثور عليه

    يتم حساب الربح/الخسارة تلقائياً بناءً على سعر الدخول والخروج.
    """
    if trade_id is None or exit_price is None:
        raise ValueError("يجب توفير معرف التداول وسعر الخروج")

    try:
        with get_session() as session:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                logger.warning(f"لم يتم العثور على تداول بالمعرف: {trade_id}")
                return None

            # حساب الربح/الخسارة
            if trade.entry_price and trade.entry_price > 0:
                eff_shares = trade.shares or 1
                trade.pnl = round((exit_price - trade.entry_price) * eff_shares, 2)
                trade.pnl_pct = round(((exit_price - trade.entry_price) / trade.entry_price) * 100, 2)
            else:
                trade.pnl = 0.0
                trade.pnl_pct = 0.0

            # تحديث بيانات الإغلاق
            trade.exit_price = exit_price
            trade.exit_reason = reason
            trade.exit_date = datetime.utcnow()
            trade.status = "closed"
            trade.updated_at = datetime.utcnow()

            result = trade.to_dict()
            logger.info(
                f"تم إغلاق تداول: {trade.symbol} - معرف: {trade_id} - "
                f"ربح/خسارة: {trade.pnl:.2f} ({trade.pnl_pct:.2f}%)"
            )
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في إغلاق التداول {trade_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في إغلاق التداول {trade_id}: {e}")
        raise


def delete_trade(trade_id: int) -> bool:
    """
    حذف تداول محدد
    Delete a specific trade

    Args:
        trade_id: معرف التداول المراد حذفه

    Returns:
        True إذا تم الحذف بنجاح، False إذا لم يتم العثور على التداول
    """
    if trade_id is None:
        raise ValueError("يجب توفير معرف التداول")

    try:
        with get_session() as session:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                logger.warning(f"لم يتم العثور على تداول بالمعرف: {trade_id}")
                return False

            session.delete(trade)
            logger.info(f"تم حذف التداول: معرف: {trade_id} - رمز: {trade.symbol}")
            return True
    except SQLAlchemyError as e:
        logger.error(f"خطأ في حذف التداول {trade_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في حذف التداول {trade_id}: {e}")
        raise


# =============================================================================
# عمليات سجل الإشارات
# Signal log operations
# =============================================================================

def log_signal(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    تسجيل إشارة جديدة في السجل
    Log a new signal

    Args:
        signal: قاموس بيانات الإشارة. الحقول المتوقعة:
                symbol, action, price, reason, score, signal_type

    Returns:
        قاموس الإشارة المسجلة مع المعرف الجديد
    """
    if not signal or not signal.get("symbol"):
        logger.warning("محاولة تسجيل إشارة بدون رمز سهم - تم التجاهل")
        return None

    try:
        with get_session() as session:
            new_signal = SignalLog(
                symbol=signal.get("symbol", ""),
                action=signal.get("action", "hold"),
                price=signal.get("price"),
                reason=signal.get("reason", ""),
                score=signal.get("score", 0.0),
                signal_type=signal.get("signal_type", ""),
                entry_price=signal.get("entry_price"),
                stop_loss=signal.get("stop_loss"),
                trade_quality=signal.get("trade_quality"),
                adx=signal.get("adx"),
                rsi=signal.get("rsi"),
                entry_scenario=signal.get("entry_scenario"),
                shares=signal.get("shares"),
                card_data=signal.get("card_data"),
            )
            session.add(new_signal)
            session.flush()
            result = new_signal.to_dict()
            result["db_id"] = new_signal.id  # إرجاع معرف السجل للربط
            logger.info(
                f"تم تسجيل إشارة: {signal.get('symbol')} - "
                f"إجراء: {signal.get('action')} - نوع: {signal.get('signal_type')}"
            )
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تسجيل الإشارة: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تسجيل الإشارة: {e}")
        raise


def update_signal_result(signal_log_id: int, result: str, pnl: float, pnl_pct: float, exit_price: float, exit_reason: str) -> bool:
    """
    تحديث نتيجة إشارة في السجل (للباك تيست)
    Update signal log with trade result

    Args:
        signal_log_id: معرف سجل الإشارة
        result: WIN أو LOSS
        pnl: الربح/الخسارة بالقيمة المطلقة
        pnl_pct: نسبة الربح/الخسارة
        exit_price: سعر الخروج
        exit_reason: سبب الخروج (STOP, TARGETS, إلخ)

    Returns:
        True إذا تم التحديث بنجاح، False خلاف ذلك
    """
    if not signal_log_id:
        return False
    try:
        with get_session() as session:
            sig = session.query(SignalLog).filter(SignalLog.id == signal_log_id).first()
            if not sig:
                logger.warning(f"لم يتم العثور على سجل إشارة بالمعرف {signal_log_id}")
                return False
            sig.result = result
            sig.pnl = round(pnl, 2)
            sig.pnl_pct = round(pnl_pct, 2)
            sig.exit_price = exit_price
            sig.exit_reason = exit_reason
            sig.exit_date = datetime.utcnow()
            logger.info(f"تم تحديث نتيجة إشارة {sig.symbol}: {result} (P&L: {pnl:.2f})")
            return True
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تحديث نتيجة الإشارة {signal_log_id}: {e}")
        return False


def load_signals_log(limit: int = 200) -> List[Dict[str, Any]]:
    """
    تحميل سجل الإشارات
    Load signal history

    Args:
        limit: الحد الأقصى لعدد الإشارات المراد تحميلها (الافتراضي: 200)

    Returns:
        قائمة بالإشارات مرتبة بتاريخ الإنشاء (الأحدث أولاً)
    """
    if limit <= 0:
        limit = 200

    try:
        with get_session() as session:
            signals = (
                session.query(SignalLog)
                .order_by(SignalLog.created_at.desc())
                .limit(limit)
                .all()
            )
            result = [s.to_dict() for s in signals]
            logger.debug(f"تم تحميل {len(result)} إشارة من السجل (الحد: {limit})")
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تحميل سجل الإشارات: {e}")
        return []
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تحميل سجل الإشارات: {e}")
        return []


# =============================================================================
# عمليات تتبع الإشارات المُرسلة (منع التكرار)
# Sent signal operations (dedup tracking)
# =============================================================================

def mark_sent(symbol: str, signal_type: str) -> None:
    """
    تعليم إشارة كمُرسلة - لمنع إعادة الإرسال
    Mark a signal as sent - prevent re-sending

    Args:
        symbol: رمز السهم
        signal_type: نوع الإشارة

    يتم تسجيل تاريخ الإرسال تلقائياً.
    """
    if not symbol or not signal_type:
        logger.warning("محاولة تعليم إشارة بدون رمز أو نوع - تم التجاهل")
        return

    try:
        with get_session() as session:
            sent = SentSignal(
                symbol=symbol,
                signal_type=signal_type,
                sent_at=datetime.utcnow(),
            )
            session.add(sent)
            logger.debug(f"تم تعليم الإشارة كمُرسلة: {symbol} - {signal_type}")
    except SQLAlchemyError as e:
        logger.error(f"خطأ في تعليم الإشارة كمُرسلة: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في تعليم الإشارة كمُرسلة: {e}")
        raise


def was_sent(symbol: str, signal_type: str) -> bool:
    """
    التحقق مما إذا تم إرسال إشارة معينة اليوم
    Check if a specific signal was already sent today

    Args:
        symbol: رمز السهم
        signal_type: نوع الإشارة

    Returns:
        True إذا تم إرسال الإشارة اليوم، False إذا لم يتم إرسالها
    """
    if not symbol or not signal_type:
        return False

    try:
        with get_session() as session:
            # حساب بداية اليوم الحالي
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            exists = (
                session.query(SentSignal)
                .filter(
                    SentSignal.symbol == symbol,
                    SentSignal.signal_type == signal_type,
                    SentSignal.sent_at >= today_start,
                )
                .first()
            )

            result = exists is not None
            logger.debug(
                f"التحقق من إرسال إشارة: {symbol} - {signal_type} - "
                f"النتيجة: {'مرسلة' if result else 'غير مرسلة'}"
            )
            return result
    except SQLAlchemyError as e:
        logger.error(f"خطأ في التحقق من إرسال الإشارة: {e}")
        return False
    except Exception as e:
        logger.error(f"خطأ غير متوقع في التحقق من إرسال الإشارة: {e}")
        return False


def clear_sent_today() -> None:
    """
    مسح إشارات اليوم المُرسلة - لبداية يوم جديد
    Clear sent signals for new day

    يتم حذف جميع سجلات الإشارات المُرسلة من اليوم الحالي.
    يُستدعى عادةً عند بداية يوم تداول جديد.
    """
    try:
        with get_session() as session:
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            deleted = (
                session.query(SentSignal)
                .filter(SentSignal.sent_at >= today_start)
                .delete()
            )

            logger.info(f"تم مسح {deleted} إشارة مُرسلة من اليوم")
    except SQLAlchemyError as e:
        logger.error(f"خطأ في مسح الإشارات المُرسلة: {e}")
        raise
    except Exception as e:
        logger.error(f"خطأ غير متوقع في مسح الإشارات المُرسلة: {e}")
        raise


# =============================================================================
# دوال المستخدمين
# User functions
# =============================================================================

def register_user(username: str, email: str, password_hash: str, role: str = "user", confirmation_token: str = None, confirmed: bool = False) -> Optional[Dict[str, Any]]:
    """تسجيل مستخدم جديد"""
    try:
        with get_session() as session:
            existing = session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            if existing:
                return None
            user = User(username=username, email=email, password_hash=password_hash, role=role, confirmation_token=confirmation_token, email_confirmed=confirmed)
            session.add(user)
            session.commit()
            logger.info(f"مستخدم جديد: {username} ({email})")
            return user.to_dict()
    except Exception as e:
        logger.error(f"خطأ في تسجيل المستخدم: {e}")
        return None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """البحث عن مستخدم باسم المستخدم"""
    try:
        with get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            return user.to_dict() if user else None
    except Exception as e:
        logger.error(f"خطأ في البحث عن المستخدم: {e}")
        return None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """البحث عن مستخدم بالبريد الإلكتروني"""
    try:
        with get_session() as session:
            user = session.query(User).filter(User.email == email).first()
            return user.to_dict() if user else None
    except Exception as e:
        logger.error(f"خطأ في البحث عن المستخدم: {e}")
        return None


def confirm_email(token: str) -> bool:
    """تأكيد البريد الإلكتروني باستخدام التوكن"""
    try:
        with get_session() as session:
            user = session.query(User).filter(User.confirmation_token == token).first()
            if not user:
                return False
            user.email_confirmed = True
            user.confirmation_token = None
            session.commit()
            logger.info(f"تم تأكيد البريد الإلكتروني للمستخدم: {user.email}")
            return True
    except Exception as e:
        logger.error(f"خطأ في تأكيد البريد: {e}")
        return False


def get_all_users() -> List[Dict[str, Any]]:
    """جلب كل المستخدمين"""
    try:
        with get_session() as session:
            return [u.to_dict() for u in session.query(User).all()]
    except Exception as e:
        logger.error(f"خطأ في جلب المستخدمين: {e}")
        return []


# =============================================================================
# دوال تتبع الزوار
# Visit tracking
# =============================================================================

ONLINE_TIMEOUT = 300  # 5 دقائق بدون نشاط = غير متصل

def log_visit(ip: str, user_agent: str = "", page: str = "/") -> bool:
    """تسجيل زيارة للموقع"""
    try:
        with get_session() as session:
            visit = Visit(ip=ip, user_agent=user_agent[:500], page=page)
            session.add(visit)
            session.commit()
            logger.debug(f"زيارة مسجلة من {ip}")
            return True
    except Exception as e:
        logger.error(f"خطأ في تسجيل الزيارة: {e}")
        return False


def get_visit_stats() -> Dict[str, Any]:
    """إحصائيات شاملة (للأدمن فقط)"""
    try:
        with get_session() as session:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=ONLINE_TIMEOUT)

            total_visits = session.query(Visit).count()
            unique_ips = session.query(Visit.ip).distinct().count()
            online_now = session.query(Visit.ip).filter(
                Visit.visited_at >= cutoff
            ).distinct().count()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_visits = session.query(Visit).filter(
                Visit.visited_at >= today_start
            ).count()

            # زيارات آخر 7 أيام (للرسم البياني)
            week_visits = []
            for i in range(6, -1, -1):
                day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                count = session.query(Visit).filter(
                    Visit.visited_at >= day_start, Visit.visited_at < day_end
                ).count()
                week_visits.append({
                    "date": day_start.strftime("%Y-%m-%d"),
                    "label": ["الأحد","الإثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"][day_start.weekday()],
                    "count": count,
                })

            # إحصائيات المستخدمين
            user_count = session.query(User).count()
            admin_count = session.query(User).filter(User.role == "admin").count()

            # إحصائيات الصفقات
            trade_count = session.query(Trade).count()
            open_trades = session.query(Trade).filter(Trade.status == "active").count()
            win_trades = session.query(Trade).filter(Trade.pnl > 0).count()
            loss_trades = session.query(Trade).filter(Trade.pnl < 0).count()

            # إحصائيات الإشارات
            signal_count = session.query(SignalLog).count()

            # آخر 5 زوار
            recent = session.query(Visit).order_by(
                Visit.visited_at.desc()
            ).limit(5).all()

            return {
                "visits": {
                    "total": total_visits,
                    "unique": unique_ips,
                    "online_now": online_now,
                    "today": today_visits,
                    "week": week_visits,
                },
                "users": {
                    "total": user_count,
                    "admins": admin_count,
                },
                "trades": {
                    "total": trade_count,
                    "open": open_trades,
                    "wins": win_trades,
                    "losses": loss_trades,
                },
                "signals": {
                    "total": signal_count,
                },
                "recent": [v.to_dict() for v in recent],
            }
    except Exception as e:
        logger.error(f"خطأ في جلب الإحصائيات: {e}")
        return {
            "visits": {"total": 0, "unique": 0, "online_now": 0, "today": 0, "week": []},
            "users": {"total": 0, "admins": 0},
            "trades": {"total": 0, "open": 0, "wins": 0, "losses": 0},
            "signals": {"total": 0},
            "recent": [],
        }


def get_all_visits(limit: int = 100) -> List[Dict[str, Any]]:
    """جلب آخر الزيارات"""
    try:
        with get_session() as session:
            visits = session.query(Visit).order_by(
                Visit.visited_at.desc()
            ).limit(limit).all()
            return [v.to_dict() for v in visits]
    except Exception as e:
        logger.error(f"خطأ في جلب الزيارات: {e}")
        return []


# =============================================================================
# دوال الأكواد المميزة
# Premium codes
# =============================================================================

def generate_premium_codes(count: int = 1, duration_days: int = 30, max_uses: int = 1,
                           created_by: str = None) -> List[Dict[str, Any]]:
    """توليد أكواد اشتراك مميز"""
    import secrets, string
    codes = []
    with get_session() as session:
        for _ in range(count):
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(12))
            pc = PremiumCode(code=code, duration_days=duration_days, max_uses=max_uses,
                             created_by=created_by)
            session.add(pc)
            codes.append(pc.to_dict())
        session.commit()
    return codes


def get_premium_codes() -> List[Dict[str, Any]]:
    """جلب كل الأكواد المميزة"""
    try:
        with get_session() as session:
            return [c.to_dict() for c in session.query(PremiumCode).order_by(PremiumCode.created_at.desc()).all()]
    except Exception as e:
        logger.error(f"خطأ في جلب الأكواد: {e}")
        return []


def _resolve_user(session, user_id: str):
    """العثور على مستخدم بالايميل أو اسم المستخدم"""
    user = session.query(User).filter(User.email == user_id).first()
    if not user:
        user = session.query(User).filter(User.username == user_id).first()
    return user


def apply_premium_code(user_id: str, code: str) -> Dict[str, Any]:
    """تطبيق كود اشتراك مميز لمستخدم"""
    with get_session() as session:
        pc = session.query(PremiumCode).filter(PremiumCode.code == code).first()
        if not pc:
            return {"ok": False, "detail": "الكود غير صحيح"}
        if not pc.is_active:
            return {"ok": False, "detail": "هذا الكود غير نشط"}
        if pc.used_count >= pc.max_uses:
            return {"ok": False, "detail": "هذا الكود استنفذ عدد الاستخدامات"}
        user = _resolve_user(session, user_id)
        if not user:
            return {"ok": False, "detail": "المستخدم غير موجود"}
        # تحديث خطة المستخدم
        now = datetime.utcnow()
        if user.premium_until and user.premium_until > now:
            user.premium_until = user.premium_until + timedelta(days=pc.duration_days)
        else:
            user.premium_until = now + timedelta(days=pc.duration_days)
        user.plan = "premium"
        pc.used_count += 1
        used_list = (pc.used_by or "").split(",")
        if user_id not in used_list:
            used_list.append(user_id)
        pc.used_by = ",".join(filter(None, used_list))
        session.commit()
        return {"ok": True, "plan": user.plan, "premium_until": user.premium_until.isoformat()}


def cancel_premium(user_id: str) -> bool:
    """إلغاء الاشتراك المميز لمستخدم"""
    try:
        with get_session() as session:
            user = _resolve_user(session, user_id)
            if not user:
                return False
            user.plan = "free"
            user.premium_until = None
            session.commit()
            return True
    except Exception as e:
        logger.error(f"خطأ في إلغاء الاشتراك: {e}")
        return False
