import sys, os, json, logging, time, re, ssl, hashlib, hmac, urllib.parse, gzip
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from collections import defaultdict
from io import StringIO
from pathlib import Path
import requests
import numpy as np
import pandas as pd

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
CAIRO_TZ_OFFSET = 2  # متغير — يستخدم التوقيت الفعلي من ZoneInfo

# الحصول على توقيت القاهرة الحالي مع مراعاة التوقيت الصيفي/الشتوي تلقائياً
CAIRO_TZ = ZoneInfo("Africa/Cairo")
def cairo_now() -> datetime:
    """ترجع الوقت الحالي بتوقيت القاهرة (مع DST التلقائي)"""
    return datetime.now(CAIRO_TZ)

RISK_DISCLAIMER = """
⚠️ تنويه مخاطر مهم
هذا التطبيق للأغراض التعليمية والبحثية فقط ولا يعتبر استشارة مالية.
قرارات التداول الآلية تحمل مخاطر مالية كبيرة وقد تؤدي إلى خسارة رأس المال.
المستخدم يتحمل المسؤولية الكاملة عن قراراته الاستثمارية.
لا تداول بأموال لا تتحمل خسارتها.
"""

TRADE_MODE_AUTO = "auto"
from database import *
TRADE_MODE_AUTO = "auto"
TRADE_MODE_SEMI = "semi_auto"
TRADE_MODE_MANUAL = "manual"

# ══════════════════════════════════════════════════════════════════════════════
# Security Module - وحدة الأمان
# ══════════════════════════════════════════════════════════════════════════════



import os
import json
import base64
import logging
import ssl
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import bcrypt

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# إعدادات الأمان من متغيرات البيئة
# Security configuration from environment variables
# ──────────────────────────────────────────────────────────────────────────────

SECRET_KEY: str = os.getenv("EGX_SECRET_KEY", "egx-v2-change-this-secret-key-in-production-64bytes!!")
"""المفتاح السري لتوقيع رموز JWT - يُفضل تغييره في بيئة الإنتاج"""

JWT_ALGORITHM: str = "HS256"
"""خوارزمية التوقيع المستخدمة لرموز JWT"""

JWT_EXPIRY_HOURS: int = int(os.getenv("EGX_JWT_EXPIRY_HOURS", "24"))
"""مدة صلاحية رمز JWT بالساعات"""

ENCRYPTION_SALT: bytes = os.getenv("EGX_ENCRYPTION_SALT", "egx-v2-salt").encode()
"""ملح التشفير المستخدم في اشتقاق المفاتيح من كلمات المرور"""

PBKDF2_ITERATIONS: int = 480_000
"""عدد تكرارات PBKDF2 - يُوصى بـ ٤٨٠,٠٠٠ تكرار وفقاً لمعايير OWASP 2023"""


# ══════════════════════════════════════════════════════════════════════════════
# تجزئة كلمات المرور - Password Hashing
# ══════════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """
    تجزئة كلمة المرور باستخدام خوارزمية bcrypt

    تقوم هذه الدالة بتجزئة كلمة المرور باستخدام bcrypt مع توليد ملح عشوائي
    تلقائياً. النتيجة تحتوي على الملح والتجزئة معاً مما يسهل التحقق لاحقاً.

    المعطيات:
        password: كلمة المرور النصية العادية

    المخرجات:
        سلسلة نصية تحتوي على تجزئة bcrypt لكلمة المرور

    الأخطاء:
        TypeError: إذا كان المعطى ليس سلسلة نصية
        ValueError: إذا كانت كلمة المرور فارغة

    مثال:
        >>> hashed = hash_password("my_secret_password")
        >>> isinstance(hashed, str)
        True
    """
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    # تحويل كلمة المرور إلى بايتات لتتوافق مع bcrypt
    password_bytes = password.encode("utf-8")

    # توليد الملح وتجزئة كلمة المرور
    # عامل التكلفة الافتراضي هو ١٢ وهو توازن جيد بين الأمان والأداء
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(password_bytes, salt)

    # إرجاع النتيجة كسلسلة نصية
    return hashed_bytes.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """
    التحقق من صحة كلمة المرور مقابل التجزئة المخزنة

    تقارن هذه الدالة كلمة المرور النصية العادية مع التجزئة المخزنة
    باستخدام خوارزمية bcrypt.

    المعطيات:
        password: كلمة المرور النصية العادية للتحقق منها
        hashed: التجزئة المخزنة لكلمة المرور (من دالة hash_password)

    المخرجات:
        True إذا تطابقت كلمة المرور، False خلاف ذلك

    مثال:
        >>> hashed = hash_password("my_secret_password")
        >>> verify_password("my_secret_password", hashed)
        True
        >>> verify_password("wrong_password", hashed)
        False
    """
    if not isinstance(password, str) or not isinstance(hashed, str):
        logger.warning("معطيات غير صالحة للتحقق من كلمة المرور: يجب أن تكون سلاسل نصية")
        return False

    try:
        password_bytes = password.encode("utf-8")
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except ValueError as exc:
        # يحدث هذا عندما تكون التجزئة بتنسيق غير صالح
        logger.error("تنسيق تجزئة كلمة المرور غير صالح: %s", exc)
        return False
    except TypeError as exc:
        # يحدث هذا عندما تكون أنواع المعطيات غير متوقعة
        logger.error("نوع معطى غير متوقع أثناء التحقق من كلمة المرور: %s", exc)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# المصادقة برموز JWT - JWT Authentication
# ══════════════════════════════════════════════════════════════════════════════

def create_jwt_token(user_id: str, role: str = "user") -> str:
    """
    إنشاء رمز مصادقة JWT للمستخدم

    تقوم هذه الدالة بإنشاء رمز JWT يحتوي على معرف المستخدم والدور
    وتاريخ الانتهاء وتاريخ الإنشاء. يُوقَّع الرمز باستخدام المفتاح السري.

    المعطيات:
        user_id: المعرف الفريد للمستخدم
        role: دور المستخدم (افتراضي: "user")، يمكن أن يكون "admin" أو "analyst"

    المخرجات:
        رمز JWT مشفر كسلسلة نصية

    الأخطاء:
        TypeError: إذا كان معرف المستخدم ليس سلسلة نصية
        ValueError: إذا كان معرف المستخدم فارغاً

    مثال:
        >>> token = create_jwt_token("user_123", role="analyst")
        >>> isinstance(token, str)
        True
    """
    if not isinstance(user_id, str):
        raise TypeError("معرف المستخدم يجب أن يكون سلسلة نصية")
    if not user_id:
        raise ValueError("معرف المستخدم لا يمكن أن يكون فارغاً")

    # حساب وقت انتهاء الصلاحية
    now = datetime.utcnow()
    expiry = now + timedelta(hours=JWT_EXPIRY_HOURS)

    # بناء حمولة الرمز
    payload: Dict[str, Any] = {
        "sub": user_id,          # الموضوع - معرف المستخدم
        "role": role,            # دور المستخدم
        "iat": now,              # وقت الإصدار
        "exp": expiry,           # وقت الانتهاء
    }

    try:
        # إنشاء الرمز المُوقَّع
        token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
        logger.info("تم إنشاء رمز JWT بنجاح للمستخدم: %s (دور: %s)", user_id, role)
        return token
    except Exception as exc:
        logger.error("فشل إنشاء رمز JWT للمستخدم %s: %s", user_id, exc)
        raise RuntimeError(f"فشل إنشاء رمز المصادقة: {exc}") from exc


def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    التحقق من صحة رمز JWT وفك تشفيره

    تقوم هذه الدالة بالتحقق من توقيع رمز JWT وصلاحيته الزمنية
    ثم تعيد حمولة الرمز إذا كان صالحاً.

    المعطيات:
        token: رمز JWT كسلسلة نصية

    المخرجات:
        قاموس يحتوي على حمولة الرمز إذا كان صالحاً، أو None إذا كان غير صالح أو منتهي الصلاحية

    مثال:
        >>> token = create_jwt_token("user_123")
        >>> payload = verify_jwt_token(token)
        >>> payload["sub"]
        'user_123'
        >>> payload["role"]
        'user'
    """
    if not isinstance(token, str) or not token:
        logger.warning("رمز JWT فارغ أو ليس سلسلة نصية")
        return None

    try:
        # فك تشفير الرمز والتحقق من التوقيع والصلاحية
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        logger.debug("تم التحقق بنجاح من رمز JWT للمستخدم: %s", payload.get("sub"))
        return payload

    except jwt.ExpiredSignatureError:
        # الرمز منتهي الصلاحية
        logger.warning("رمز JWT منتهي الصلاحية")
        return None

    except jwt.InvalidSignatureError:
        # التوقيع غير صالح - محاولة تلاعب محتملة
        logger.warning("توقيع رمز JWT غير صالح - محاولة وصول غير مصرح بها")
        return None

    except jwt.DecodeError as exc:
        # الرمز بتنسيق غير صالح
        logger.warning("فشل فك تشفير رمز JWT: %s", exc)
        return None

    except jwt.InvalidTokenError as exc:
        # أي خطأ آخر متعلق بالرمز
        logger.warning("رمز JWT غير صالح: %s", exc)
        return None

    except Exception as exc:
        # خطأ غير متوقع - يجب تسجيله كمستوى خطأ
        logger.error("خطأ غير متوقع أثناء التحقق من رمز JWT: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# تشفير البيانات - Data Encryption (PBKDF2 + Fernet)
# ══════════════════════════════════════════════════════════════════════════════

def derive_key(password: str) -> bytes:
    """
    اشتقاق مفتاح تشفير Fernet من كلمة مرور باستخدام PBKDF2

    تستخدم هذه الدالة خوارزمية PBKDF2-HMAC-SHA256 لاشتقاق مفتاح
    تشفير بطول ٣٢ بايت مناسب لخوارزمية Fernet. يتم استخدام الملح
    وعدد التكرارات المُعرَّفين في إعدادات الوحدة.

    المعطيات:
        password: كلمة المرور المستخدمة لاشتقاق المفتاح

    المخرجات:
        مفتاح تشفير كبايتات بصيغة base64url (٣٢ بايت مشفرة)

    الأخطاء:
        TypeError: إذا كان المعطى ليس سلسلة نصية
        ValueError: إذا كانت كلمة المرور فارغة

    ملاحظة:
        المفتاح المُشتق يعتمد على كلمة المرور والملح وعدد التكرارات.
        تغيير أي منها سيؤدي إلى مفتاح مختلف ولن يمكن فك التشفير.

    مثال:
        >>> key = derive_key("my_encryption_password")
        >>> isinstance(key, bytes)
        True
    """
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    # إعداد دالة اشتقاق المفاتيح
    # SHA256 هي دالة التجزئة الموصى بها لـ PBKDF2
    # طول المفتاح ٣٢ بايت وهو المطلوب لخوارزمية Fernet (AES-128)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=ENCRYPTION_SALT,
        iterations=PBKDF2_ITERATIONS,
    )

    # اشتقاق المفتاح وتشفيره بصيغة base64url
    key = kdf.derive(password.encode("utf-8"))

    # Fernet يتطلب المفتاح بصيغة base64url مشفر
    return base64.urlsafe_b64encode(key)


def encrypt_data(data: str, password: str) -> str:
    """
    تشفير بيانات نصية باستخدام PBKDF2 + Fernet

    تقوم هذه الدالة بتشفير سلسلة نصية باستخدام مفتاح مُشتق من كلمة المرور
    عبر خوارزمية PBKDF2 ثم خوارزمية التشفير المتماثل Fernet (AES-128-CBC).

    المعطيات:
        data: البيانات النصية المراد تشفيرها
        password: كلمة المرور المستخدمة لتشفير البيانات

    المخرجات:
        سلسلة نصية مشفرة بصيغة base64

    الأخطاء:
        TypeError: إذا كان أي من المعطيات ليس سلسلة نصية
        ValueError: إذا كان أي من المعطيات فارغاً

    مثال:
        >>> encrypted = encrypt_data("بيانات سرية", "my_password")
        >>> isinstance(encrypted, str)
        True
    """
    if not isinstance(data, str):
        raise TypeError("البيانات يجب أن تكون سلسلة نصية")
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not data:
        raise ValueError("البيانات لا يمكن أن تكون فارغة")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    try:
        # اشتقاق مفتاح التشفير من كلمة المرور
        key = derive_key(password)

        # إنشاء كائن Fernet بالمفتاح المُشتق
        fernet = Fernet(key)

        # تشفير البيانات
        encrypted_bytes = fernet.encrypt(data.encode("utf-8"))

        # إرجاع النتيجة كسلسلة نصية
        return encrypted_bytes.decode("utf-8")

    except Exception as exc:
        logger.error("فشل تشفير البيانات: %s", exc)
        raise RuntimeError(f"فشل تشفير البيانات: {exc}") from exc


def decrypt_data(encrypted: str, password: str) -> str:
    """
    فك تشفير بيانات نصية مشفرة باستخدام PBKDF2 + Fernet

    تقوم هذه الدالة بفك تشفير سلسلة نصية مشفرة باستخدام نفس كلمة المرور
    المستخدمة في التشفير.

    المعطيات:
        encrypted: البيانات المشفرة بصيغة base64 (من دالة encrypt_data)
        password: كلمة المرور المستخدمة في التشفير الأصلي

    المخرجات:
        البيانات الأصلية المفكوكة التشفير كسلسلة نصية

    الأخطاء:
        TypeError: إذا كان أي من المعطيات ليس سلسلة نصية
        ValueError: إذا كان أي من المعطيات فارغاً
        RuntimeError: إذا فشل فك التشفير (كلمة مرور خاطئة أو بيانات تالفة)

    مثال:
        >>> encrypted = encrypt_data("بيانات سرية", "my_password")
        >>> decrypt_data(encrypted, "my_password")
        'بيانات سرية'
    """
    if not isinstance(encrypted, str):
        raise TypeError("البيانات المشفرة يجب أن تكون سلسلة نصية")
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not encrypted:
        raise ValueError("البيانات المشفرة لا يمكن أن تكون فارغة")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    try:
        # اشتقاق مفتاح التشفير من كلمة المرور
        key = derive_key(password)

        # إنشاء كائن Fernet بالمفتاح المُشتق
        fernet = Fernet(key)

        # فك تشفير البيانات
        decrypted_bytes = fernet.decrypt(encrypted.encode("utf-8"))

        # إرجاع النتيجة كسلسلة نصية
        return decrypted_bytes.decode("utf-8")

    except InvalidToken as exc:
        # فشل فك التشفير - كلمة المرور خاطئة أو البيانات تالفة
        logger.warning("فشل فك التشفير: كلمة مرور خاطئة أو بيانات تالفة")
        raise RuntimeError(
            "فشل فك التشفير: كلمة المرور خاطئة أو البيانات تالفة أو منتهية الصلاحية"
        ) from exc

    except Exception as exc:
        logger.error("خطأ غير متوقع أثناء فك التشفير: %s", exc)
        raise RuntimeError(f"فشل فك تشفير البيانات: {exc}") from exc


def encrypt_json(data: dict, password: str) -> str:
    """
    تشفير قاموس بيانات JSON باستخدام PBKDF2 + Fernet

    تقوم هذه الدالة بتحويل القاموس إلى سلسلة JSON ثم تشفيرها.

    المعطيات:
        data: القاموس المراد تشفيره
        password: كلمة المرور المستخدمة للتشفير

    المخرجات:
        سلسلة نصية مشفرة بصيغة base64 تحتوي على بيانات JSON المشفرة

    الأخطاء:
        TypeError: إذا كانت البيانات ليست قاموساً أو كلمة المرور ليست سلسلة نصية
        ValueError: إذا كانت البيانات أو كلمة المرور فارغة
        RuntimeError: إذا فشل تحويل البيانات إلى JSON أو فشل التشفير

    مثال:
        >>> encrypted = encrypt_json({"اسم": "أحمد", "رصيد": 50000}, "my_password")
        >>> isinstance(encrypted, str)
        True
    """
    if not isinstance(data, dict):
        raise TypeError("البيانات يجب أن تكون قاموساً (dict)")
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not data:
        raise ValueError("القاموس لا يمكن أن يكون فارغاً")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    try:
        # تحويل القاموس إلى سلسلة JSON
        # ensure_ascii=False لدعم الأحرف العربية وغير الإنجليزية
        json_string = json.dumps(data, ensure_ascii=False, sort_keys=True)

        # تشفير سلسلة JSON
        return encrypt_data(json_string, password)

    except (TypeError, OverflowError) as exc:
        # فشل تحويل القاموس إلى JSON (مثلاً يحتوي على أنواع غير قابلة للتحويل)
        logger.error("فشل تحويل البيانات إلى JSON: %s", exc)
        raise RuntimeError(f"فشل تحويل البيانات إلى JSON: {exc}") from exc

    except RuntimeError:
        # إعادة رفع خطأ التشفير من encrypt_data مباشرة
        raise

    except Exception as exc:
        logger.error("خطأ غير متوقع أثناء تشفير JSON: %s", exc)
        raise RuntimeError(f"فشل تشفير بيانات JSON: {exc}") from exc


def decrypt_json(encrypted: str, password: str) -> dict:
    """
    فك تشفير بيانات JSON المشفرة وإرجاعها كقاموس

    تقوم هذه الدالة بفك تشفير السلسلة المشفرة ثم تحويلها من JSON إلى قاموس.

    المعطيات:
        encrypted: السلسلة المشفرة بصيغة base64 (من دالة encrypt_json)
        password: كلمة المرور المستخدمة في التشفير الأصلي

    المخرجات:
        القاموس الأصلي المفكوك التشفير

    الأخطاء:
        TypeError: إذا كانت المعطيات ليست بالأنواع الصحيحة
        ValueError: إذا كانت المعطيات فارغة
        RuntimeError: إذا فشل فك التشفير أو فشل تحويل JSON إلى قاموس

    مثال:
        >>> encrypted = encrypt_json({"اسم": "أحمد", "رصيد": 50000}, "my_password")
        >>> decrypt_json(encrypted, "my_password")
        {'اسم': 'أحمد', 'رصيد': 50000}
    """
    if not isinstance(encrypted, str):
        raise TypeError("البيانات المشفرة يجب أن تكون سلسلة نصية")
    if not isinstance(password, str):
        raise TypeError("كلمة المرور يجب أن تكون سلسلة نصية")
    if not encrypted:
        raise ValueError("البيانات المشفرة لا يمكن أن تكون فارغة")
    if not password:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")

    try:
        # فك تشفير السلسلة للحصول على JSON النصي
        json_string = decrypt_data(encrypted, password)

        # تحويل JSON إلى قاموس
        result = json.loads(json_string)

        # التحقق من أن النتيجة قاموس
        if not isinstance(result, dict):
            raise ValueError(
                f"البيانات المفكوكة ليست قاموساً بل من نوع: {type(result).__name__}"
            )

        return result

    except json.JSONDecodeError as exc:
        # البيانات المفكوكة ليست JSON صالح
        logger.error("فشل تحليل JSON بعد فك التشفير: %s", exc)
        raise RuntimeError(f"البيانات المفكوكة ليست JSON صالح: {exc}") from exc

    except (ValueError, RuntimeError):
        # إعادة رفع أخطاء التحقق وفك التشفير مباشرة
        raise

    except Exception as exc:
        logger.error("خطأ غير متوقع أثناء فك تشفير JSON: %s", exc)
        raise RuntimeError(f"فشل فك تشفير بيانات JSON: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# إعداد SSL - SSL Configuration
# ══════════════════════════════════════════════════════════════════════════════

def get_ssl_context() -> ssl.SSLContext:
    """
    إنشاء سياق SSL آمن للاتصالات المشفرة

    تقوم هذه الدالة بإنشاء سياق SSL مُعد بشكل آمن مع:
    - تعطيل البروتوكولات القديمة (SSLv2, SSLv3)
    - استخدام شهادات CA من مكتبة certifi
    - تفعيل التحقق من شهادة المضيف

    المخرجات:
        كائن ssl.SSLContext مُعد بإعدادات أمان متقدمة

    ملاحظة:
        تتطلب هذه الدالة تثبيت مكتبة certifi.
        إذا لم تكن متاحة، يتم استخدام شهادات النظام الافتراضية.

    مثال:
        >>> ctx = get_ssl_context()
        >>> ctx.minimum_version.name
        'TLSv1_2'
    """
    # إنشاء سياق SSL بإعدادات افتراضية آمنة
    # PROTOCOL_TLS_CLIENT يختار أعلى بروتوكول متاح
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # تعيين الحد الأدنى لبروتوكول TLS إلى 1.2
    # بروتوكولات أقدم (SSLv2, SSLv3, TLS 1.0, TLS 1.1) غير آمنة
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    # تفعيل التحقق من شهادة المضيف
    context.check_hostname = True

    # تحميل شهادات CA الموثوقة
    # نحاول أولاً استخدام certifi للحصول على أحدث الشهادات
    try:
        import certifi
        ca_certs_path = certifi.where()
        context.load_verify_locations(ca_certs_path)
        logger.info("تم تحميل شهادات CA من certifi: %s", ca_certs_path)
    except ImportError:
        # certifi غير متاح - استخدام شهادات النظام الافتراضية
        logger.warning(
            "مكتبة certifi غير متاحة - يتم استخدام شهادات النظام الافتراضية. "
            "يُنصح بتثبيت certifi للحصول على أحدث شهادات CA: pip install certifi"
        )
        context.load_default_certs()

    # تعطيل التشفيرات الضعيفة
    # تعيين مجموعة التشفير المسموحة - استخدام التشفيرات القوية فقط
    try:
        # تأكد من استخدام تشفيرات ECDHE و AES-GCM فقط
        context.set_ciphers(
            "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20"
        )
    except ssl.SSLError as exc:
        # بعض الأنظمة قد لا تدعم كل التشفيرات المحددة
        logger.warning("تعذر تعيين مجموعة التشفير المخصصة: %s", exc)

    # تم تعطيل التحقق من CRL لأنه يسبب مشاكل في كثير من البيئات
    # CRL verification disabled for broader compatibility

    logger.info("تم إنشاء سياق SSL آمن بنجاح (الحد الأدنى: TLS 1.2)")
    return context


# ══════════════════════════════════════════════════════════════════════════════
# Database Module - وحدة قاعدة البيانات
# ══════════════════════════════════════════════════════════════════════════════



import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)



# =============================================================================
# دوال مساعدة داخلية
# Internal helper functions
# =============================================================================

def _dict_to_trade(trade_data: Dict[str, Any]) -> Trade:
    """
    تحويل قاموس بيانات التداول إلى نموذج Trade
    Convert a trade dictionary to a Trade model instance

    Args:
        trade_data: قاموس بيانات التداول

    Returns:
        كائن Trade جاهز للإضافة إلى قاعدة البيانات

    ملاحظة: لا يتم تعيين المعرف (id) لأنه يتم إنشاؤه تلقائياً.
    """
    # معالجة الحقول JSON
    targets = trade_data.get("targets", [])
    if isinstance(targets, (list, dict)):
        targets_str = json.dumps(targets, ensure_ascii=False)
    elif isinstance(targets, str):
        targets_str = targets
    else:
        targets_str = "[]"

    notes = trade_data.get("notes", {})
    if isinstance(notes, (dict, list)):
        notes_str = json.dumps(notes, ensure_ascii=False)
    elif isinstance(notes, str):
        notes_str = notes
    else:
        notes_str = "{}"

    # معالجة التواريخ
    entry_date = trade_data.get("entry_date")
    if isinstance(entry_date, str):
        try:
            entry_date = datetime.fromisoformat(entry_date)
        except (ValueError, TypeError):
            entry_date = datetime.utcnow()
    elif not isinstance(entry_date, datetime):
        entry_date = datetime.utcnow()

    exit_date = trade_data.get("exit_date")
    if isinstance(exit_date, str):
        try:
            exit_date = datetime.fromisoformat(exit_date)
        except (ValueError, TypeError):
            exit_date = None
    elif not isinstance(exit_date, datetime):
        exit_date = None

    return Trade(
        symbol=trade_data.get("symbol", ""),
        entry_price=float(trade_data.get("entry_price", 0.0)),
        shares=int(trade_data.get("shares", 0)),
        q1_qty=int(trade_data.get("q1_qty", 0)) if trade_data.get("q1_qty") is not None else None,
        q2_qty=int(trade_data.get("q2_qty", 0)) if trade_data.get("q2_qty") is not None else None,
        q3_qty=int(trade_data.get("q3_qty", 0)) if trade_data.get("q3_qty") is not None else None,
        stop_loss=float(trade_data.get("stop_loss", 0.0)) if trade_data.get("stop_loss") is not None else None,
        targets=targets_str,
        status=trade_data.get("status", "active"),
        pnl=float(trade_data.get("pnl", 0.0)) if trade_data.get("pnl") is not None else None,
        pnl_pct=float(trade_data.get("pnl_pct", 0.0)) if trade_data.get("pnl_pct") is not None else None,
        exit_price=float(trade_data.get("exit_price", 0.0)) if trade_data.get("exit_price") is not None else None,
        exit_reason=trade_data.get("exit_reason"),
        signal_log_id=trade_data.get("signal_log_id"),
        notes=notes_str,
        entry_date=entry_date,
        exit_date=exit_date,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Data Fetcher Module - وحدة جلب البيانات
# ══════════════════════════════════════════════════════════════════════════════



import gzip
import json
import logging
import ssl
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ثوابت أعمدة البيانات - Data Column Constants
# ══════════════════════════════════════════════════════════════════════════════

COLS: List[str] = [
    "close", "change", "change_abs", "high", "low", "volume",                       # 0-5
    "market_cap_basic", "price_earnings_ttm", "average_volume_30d_calc",             # 6-8
    "price_52_week_high", "price_52_week_low", "open", "description",                # 9-12
    "earnings_per_share_basic_ttm", "RSI", "Recommend.All", "dividend_yield_recent", # 13-16
    "sector", "industry", "name",                                                     # 17-19
    "MACD.macd", "MACD.signal", "Stoch.K", "Stoch.D",                               # 20-23
    "ADX", "ATR", "BB.upper", "BB.lower", "BB.basis",                               # 24-28
    "relative_volume_10d_calc", "SMA20", "SMA50", "SMA200",                          # 29-32
    "EMA20", "EMA50", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.Y",        # 33-39
    "High.1M", "Low.1M", "High.3M", "Low.3M",                                       # 40-43  شموع شهرية/ربعية
    "RSI[1]", "MACD.macd[1]",                                                        # 44-45  RSI/MACD السابق
    "change_from_open",                                                               # 46
]
"""
قائمة أعمدة البيانات المطلوبة من TradingView Scanner API
يجب الحفاظ على الترتيب بدقة لأن البيانات تعاد كمصفوفة مرتبة
"""

# أعمدة EGX30 - فقط السعر والتغيير
EGX30_COLS: List[str] = ["close", "change"]


# ══════════════════════════════════════════════════════════════════════════════
# تعيينات القطاعات - Sector Mappings
# ══════════════════════════════════════════════════════════════════════════════

SECTOR_AR: Dict[str, str] = {
    "Finance": "مالي",
    "Banks": "بنوك",
    "Real Estate": "عقارات",
    "Basic Materials": "مواد أساسية",
    "Consumer Cyclical": "استهلاكي دوري",
    "Consumer Defensive": "غذاء ودفاعي",
    "Energy": "طاقة",
    "Healthcare": "صحة",
    "Industrials": "صناعة",
    "Technology": "تكنولوجيا",
    "Communication Services": "اتصالات",
    "Utilities": "مرافق",
    "": "أخرى",
}
"""
تعيين أسماء القطاعات من الإنجليزية إلى العربية
يُستخدم المفتاح الفارغ للقطاعات غير المصنفة
"""


# ══════════════════════════════════════════════════════════════════════════════
# أسماء الشركات المصرية بالعربية
# المصدر: TradingView + EGX الرسمي
# ══════════════════════════════════════════════════════════════════════════════

EGX_ARABIC_NAMES: Dict[str, str] = {
    # === بنوك وخدمات مالية ===
    "COMI": "البنك التجاري الدولي CIB",
    "CBKD": "كريدي أجريكول مصر",
    "QNBA": "بنك قناة السويس",
    "CIEB": "كريدي أجريكول مصر",
    "QNBE": "بنك قطر الوطني",
    "HDBK": "بنك التعمير والإسكان",
    "ADIB": "بنك أبو ظبي الإسلامي مصر",
    "FAIT": "بنك فيصل الإسلامي",
    "FAITA": "بنك فيصل الإسلامي",
    "SAUD": "البركة بنك مصر",
    "EXPA": "بنك التصدير والتنمية",
    "UBEE": "البنك المتحدة",
    "EGBE": "البنك المصري الخليجي",
    "SAIB": "البنك العربي الدولي",
    "CANA": "بنك قناة السويس",
    "NBKE": "بنك الكويت الوطني مصر",
    "HRHO": "إي أف جي القابضة",
    "BTFH": "بلتون القابضة",
    "EFIH": "إي فاينانس",
    "CICH": "سي أي كابيتال القابضة",
    "CCAP": "قله للاستثمارات المالية",
    "CNFN": "كونتكت المالية القابضة",
    "BINV": "بي إنفستمنتس القابضة",
    "ACAP": "إيه كابيتال القابضة",
    "ACTF": "أكت فاينانشال",
    "OFH": "أو بي فاينانشال القابضة",
    "PRMH": "بريم القابضة",
    "NAHO": "نعيم القابضة",
    "ATLC": "التوفيق للتأجير التمويلي",
    "ICLE": "الدولية للتأجير التمويلي",
    "MISR": "بنك مصر",
    "DEIN": "دلتا للتأمين",
    "MOIN": "المهندس للتأمين",
    "VALU": "يو فاينانشال",
    "AALR": "العامة لاستصلاح الأراضي",
    "AFDI": "الأهلي للتنمية والاستثمار",
    # === عقارات وتطوير ===
    "TMGH": "مجموعة طلعت مصطفى القابضة",
    "EMFD": "إعمار مصر للتنمية",
    "PHDC": "بالم هيلز للتعمير",
    "OCDI": "سوديك للتنمية",
    "MASR": "مصر الجديدة للإسكان والتعمير",
    "ZMID": "زهراء المعادي للاستثمار والتعمير",
    "PRDC": "بايونيرز بروبرتيز",
    "BONY": "بنيان للتنمية والتجارة",
    "ELKA": "القاهرة للإسكان",
    "ELSH": "الشمس للإسكان والتعمير",
    "OBRI": "العبور للاستثمار العقاري",
    "MENA": "مينا للاستثمار السياحي والعقاري",
    "NARE": "نعيم العقارية القابضة",
    "EHDR": "المصريين للإسكان والتنمية",
    "NHPS": "الإسكان للنقابات المهنية",
    "IDRE": "الإسماعيلية للتنمية العقاري",
    "UNIT": "يونايتد هاوسينج",
    "TANM": "تنمية للاستثمار العقاري",
    "RREI": "العربية للاستثمار العقاري",
    "DCRC": "دايس لكشف وتسربات",
    # === صناعة ومواد بناء ===
    "SWDY": "السويدي إلكتريك",
    "EGAL": "مصر للألومنيوم",
    "IRON": "الحديد والصلب المصرية",
    "IRAX": "العز الدخيلة للصلب",
    "ARCC": "العربية للأسمنت",
    "MCQE": "أسمنت مصر قنا",
    "SCEM": "أسمنت سيناء",
    "SUCE": "أسمنت السويس",
    "TORA": "أسمنت طره",
    "MBSC": "أسمنت بني سويف",
    "ATQA": "مصر الوطنية للصلب",
    "ECAP": "الجيما للسيراميك",
    "CERA": "ريماس للسيراميك",
    "ALEX": "أسمنت الإسكندرية",
    "ELEC": "إلكترو كابل مصر",
    "ALUM": "النصر لصناعة الألومنيوم",
    "MEGM": "العربية لصناعة الزجاج",
    "RAKT": "راكتا لصناعة الورق",
    "ENGC": "الهندسية للإنشاء والتنمية",
    "NCCW": "النصر للأعمال المدنية",
    "LCSW": "ليسيكو مصر",
    # === بتروكيماويات وأسمدة ===
    "MFPC": "موبكو للأسمدة",
    "ABUK": "أبو قير للأسمدة",
    "SKPC": "سيدي كرير للبتروكيماويات",
    "AMOC": "الإسكندرية للزيوت المعدنية",
    "KZPC": "كفر الزيات للمبيدات",
    "ICFC": "العالمية للأسمدة",
    "EGCH": "الكيماويات المصرية",
    "MICH": "كيماويات مصر",
    "PACH": "دهانات ومواد كيماوية",
    # === أغذية ومشروبات ===
    "EAST": "الشرقية للدخان",
    "EFID": "إديتا للصناعات الغذائية",
    "JUFO": "جهينة للصناعات الغذائية",
    "DOMT": "دومتي للصناعات الغذائية",
    "OLFI": "أبور للصناعات الغذائية",
    "ADPC": "الرابطة العربية (باندا)",
    "DTPP": "دلتا للطباعة والتغليف",
    "SNFC": "شرق الوطنية للأغذية",
    "INFI": "الإسماعيلية الوطنية للصناعات الغذائية",
    "AIFI": "أطلس للاستثمار والصناعات الغذائية",
    "SUGR": "دلتا السكر",
    "COSG": "القاهرة للزيوت والصابون",
    "MOSC": "مصر للزيوت والصابون",
    "ZEOT": "الزيوت المستخلصة",
    "WCDF": "وسط وغرب الدلتا للمطاحن",
    "CEFM": "وسط مصر للمطاحن",
    "SCFM": "جنوب القاهرة والجيزة للمطاحن",
    "UEFM": "مطاحن مصر العليا",
    "AFMC": "مطاحن الإسكندرية",
    "MILS": "مطاحن شمال القاهرة",
    "EDFM": "مطاحن شرق الدلتا",
    "AJWA": "أجواء للصناعات الغذائية",
    "WKOL": "وادي كوم أمبو للاستصلاح",
    "EALR": "العربية لاستصلاح الأراضي",
    # === أدوية وصحة ===
    "PHAR": "المصرية الدولية للأدوية",
    "CLHO": "مستشفى كليوباترا",
    "RMDA": "راميدا للأدوية",
    "NIPH": "النيل للأدوية",
    "MIPH": "مينا فارم للأدوية",
    "CPCI": "القاهرة للأدوية",
    "MPCI": "ميمفيس للأدوية",
    "OCPH": "أكتوبر فارما",
    "BIOC": "جلاكسو سميث كلاين",
    "AXPH": "الإسكندرية للأدوية",
    "NINH": "مستشفى النزهة الدولي",
    "ADCI": "أدوية العرب",
    "MCRO": "ماكرو جروب للأدوية",
    "SIPC": "سبأ الدولية للأدوية",
    "ISPH": "إبنسينا فارما",
    "HELI": "هليوبوليس للاستثمار",
    "AMES": "مركز الإسكندرية الطبي الجديد",
    # === اتصالات وتكنولوجيا ===
    "ETEL": "المصرية للاتصالات",
    "FWRY": "فوري للتكنولوجيا المالية",
    "SCTS": "قناة السويس للتكنولوجيا",
    "EGSA": "النيل للأقمار الصناعية",
    "GTHE": "جلوبال تيليكوم القابضة",
    "OIH": "أوراسكوم للاستثمار القابضة",
    "RAYA": "راية القابضة",
    # === خدمات ونقل ===
    "ALCN": "الإسكندرية للحاويات",
    "ORAS": "أوراسكوم للإنشاء",
    "GPPL": "جولدن هرم بلازا",
    "ORHD": "أوراسكوم للتنمية مصر",
    "CSAG": "قناة السويس للوكالات",
    "ETRS": "النقل والتجارة المصرية",
    "MPRC": "مدينة الإنتاج الإعلامي",
    "SPHT": "الشمس للفنادق",
    "MHOT": "مصر للفنادق",
    "PHTV": "بيراميزا للفنادق",
    "EITP": "المشروعات السياحية المصرية",
    "SDTI": "شرم دريمز للسياحة",
    "GGCC": "الجيزة العامة للمقاولات",
    "UEGC": "السعيد للمقاولات",
    "RTVC": "ريمكو للقرى السياحية",
    "NDRL": "الحفر الوطنية",
    # === طاقة ومرافق ===
    "TAQA": "طاقة عربية",
    "EGAS": "مصر للغاز",
    "MOIL": "مريدايف للخدمات البترولية",
    "AMIA": "عرب مولتاقا للاستثمارات",
    # === صناعات أخرى ===
    "ORWE": "السجاد الشرقي (أورينتال ويفرز)",
    "SPIN": "الإسكندرية للغزل والنسيج",
    "KABO": "النصر للملابس والنسيج",
    "APSW": "البولفارا العربية للغزل والنسيج",
    "DSCW": "دايس للملابس الرياضية",
    "POUL": "القاهرة للدواجن",
    "ISMA": "الإسماعيلية للدواجن",
    "SVCE": "جنوب الوادي للأسمنت",
    "CFGH": "كونكريت فاشون جروب",
    "AMER": "عامر جروب القابضة",
    "GDWA": "جدوى للتنمية الصناعية",
    "MTIE": "مجموعة إم إم للصناعة",
    "SMFR": "سماد مصر (إيجيفرت)",
    "MAAL": "مارسيليا المصرية الخليجية",
    "ARAB": "عرب ديفيلوبرز القابضة",
    "GSSC": "الصوامع والتخزين",
    "MFSC": "مصر للأسواق الحرة",
}



# ══════════════════════════════════════════════════════════════════════════════
# دوال حالة السوق - Market Status Functions
# ══════════════════════════════════════════════════════════════════════════════

def is_trading_hours() -> bool:
    """
    التحقق مما إذا كانت ساعات التداول الحالية ضمن أوقات عمل البورصة المصرية

    ساعات التداول في البورصة المصرية:
    - من الأحد إلى الخميس (أيام العمل في مصر)
    - من الساعة 10:00 صباحاً حتى 2:30 مساءً بتوقيت القاهرة

    المخرجات:
        True إذا كان السوق مفتوحاً، False خلاف ذلك
    """
    # الوقت الحالي بتوقيت القاهرة (مع مراعاة DST تلقائياً)
    now = cairo_now()

    # يوم الجمعة = 4، يوم السبت = 5 (عطلة نهاية الأسبوع في مصر)
    if now.weekday() >= 4:
        return False

    # تحويل الوقت إلى دقائق منذ منتصف الليل
    minutes_since_midnight = now.hour * 60 + now.minute

    # 10:00 = 600 دقيقة، 14:30 = 870 دقيقة
    return 600 <= minutes_since_midnight <= 870


def market_status() -> Tuple[str, str]:
    """
    الحصول على حالة السوق الحالية كنص عربي ورمز إنجليزي

    المخرجات:
        tuple من (نص_عربي, رمز_إنجليزي) حيث:
        - نص_عربي: وصف حالة السوق بالعربية
        - رمز_إنجليزي: رمز حالة السوق بالإنجليزية

    الرموز الممكنة:
        - OPEN: السوق مفتوح للتداول
        - PRE_MARKET: قبل افتتاح السوق
        - CLOSED_WEEKEND: عطلة نهاية الأسبوع
        - CLOSED_EOD: انتهى التداول لليوم
    """
    # الوقت الحالي بتوقيت القاهرة (مع مراعاة DST تلقائياً)
    now = cairo_now()
    weekday = now.weekday()

    # التحقق من عطلة نهاية الأسبوع (الجمعة 4, السبت 5)
    if weekday in (4, 5):
        return "مغلق — عطلة", "CLOSED_WEEKEND"

    # حساب الوقت بالدقائق
    minutes_since_midnight = now.hour * 60 + now.minute

    if minutes_since_midnight < 600:
        # قبل الافتتاح - حساب الوقت المتبقي
        remaining = 600 - minutes_since_midnight
        hours_left = remaining // 60
        mins_left = remaining % 60
        return (
            f"قبل الافتتاح — يفتح بعد {hours_left}س {mins_left}د",
            "PRE_MARKET",
        )
    elif minutes_since_midnight <= 870:
        # السوق مفتوح
        return "مفتوح", "OPEN"
    else:
        # انتهى التداول لليوم
        return "مغلق — انتهى التداول", "CLOSED_EOD"


# ══════════════════════════════════════════════════════════════════════════════
# فئة البيانات الأساسية للسهم - Stock Data Dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StockData:
    """
    فئة بيانات السهم - تحتوي على جميع البيانات المطلوبة لسهم واحد

    تُستخدم هذه الفئة لتخزين بيانات السهم بشكل منظم مع أنواع محددة
    لكل حقل مما يسهل الوصول والمعالجة.
    """
    # بيانات أساسية
    symbol: str = ""
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change_abs: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[float] = None
    open_p: Optional[float] = None

    # بيانات السوق
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    avg_vol: Optional[float] = None
    high52w: Optional[float] = None
    low52w: Optional[float] = None

    # معلومات الشركة
    name_en: str = ""
    tv_name: str = ""
    sector_en: str = ""
    sector: str = "أخرى"
    industry: str = ""

    # مؤشرات فنية
    rsi: Optional[float] = None
    rsi_prev: Optional[float] = None
    rating: Optional[str] = None
    rec_raw: Optional[float] = None
    div_yield: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_prev: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    adx: Optional[float] = None
    atr: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_basis: Optional[float] = None

    # المتوسطات المتحركة
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    rel_vol: Optional[float] = None

    # الأداء
    perf_w: Optional[float] = None
    perf_1m: Optional[float] = None
    perf_3m: Optional[float] = None
    perf_6m: Optional[float] = None
    perf_y: Optional[float] = None

    # أعلى وأدنى مستويات شهرية/ربعية
    high1m: Optional[float] = None
    low1m: Optional[float] = None
    high3m: Optional[float] = None
    low3m: Optional[float] = None

    # بيانات إضافية
    chg_from_open: Optional[float] = None
    price_prev: Optional[float] = None
    eps: Optional[float] = None  # earnings_per_share_basic_ttm (العمود 13)

    # بيانات EGX30 للمقارنة
    egx30_chg: Optional[float] = None

    # مصدر البيانات
    source: str = "TradingView"

    # بيانات التحليل (يتم ملؤها لاحقاً بواسطة محرك التحليل)
    analysis: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """تحويل بيانات السهم إلى قاموس"""
        return {
            "symbol": self.symbol,
            "price": self.price,
            "change_pct": self.change_pct,
            "change_abs": self.change_abs,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "volume": self.volume,
            "open_p": self.open_p,
            "market_cap": self.market_cap,
            "pe": self.pe,
            "avg_vol": self.avg_vol,
            "high52w": self.high52w,
            "low52w": self.low52w,
            "name_en": self.name_en,
            "tv_name": self.tv_name,
            "sector_en": self.sector_en,
            "sector": self.sector,
            "industry": self.industry,
            "rsi": self.rsi,
            "rsi_prev": self.rsi_prev,
            "rating": self.rating,
            "rec_raw": self.rec_raw,
            "div_yield": self.div_yield,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_prev": self.macd_prev,
            "stoch_k": self.stoch_k,
            "stoch_d": self.stoch_d,
            "adx": self.adx,
            "atr": self.atr,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "bb_basis": self.bb_basis,
            "sma20": self.sma20,
            "sma50": self.sma50,
            "sma200": self.sma200,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "rel_vol": self.rel_vol,
            "perf_w": self.perf_w,
            "perf_1m": self.perf_1m,
            "perf_3m": self.perf_3m,
            "perf_6m": self.perf_6m,
            "perf_y": self.perf_y,
            "high1m": self.high1m,
            "low1m": self.low1m,
            "high3m": self.high3m,
            "low3m": self.low3m,
            "chg_from_open": self.chg_from_open,
            "price_prev": self.price_prev,
            "eps": self.eps,
            "_egx30_chg": self.egx30_chg,
            "source": self.source,
            "analysis": self.analysis,
        }


# ══════════════════════════════════════════════════════════════════════════════
# فئة مجردة لمصدر البيانات - Abstract DataSource Class
# ══════════════════════════════════════════════════════════════════════════════

class DataSource(ABC):
    """
    فئة مجردة تحدد واجهة مصادر بيانات سوق الأسهم

    يجب أن يُنفذ كل مصدر بيانات هذه الواجهة لتوفير:
    - جلب بيانات جميع الأسهم
    - جلب بيانات المؤشرات (مثل EGX30)
    - اسم المصدر
    - التحقق من الاتصال

    أمثلة على مصادر البيانات:
    - TradingView Scanner API
    - Yahoo Finance API
    - مصادر محلية (قاعدة بيانات)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """اسم مصدر البيانات"""
        ...

    @abstractmethod
    def fetch_all_stocks(self) -> Dict[str, StockData]:
        """
        جلب بيانات جميع الأسهم المتاحة من المصدر

        المخرجات:
            قاموس حيث المفتاح هو رمز السهم والقيمة هي كائن StockData
        """
        ...

    @abstractmethod
    def fetch_index(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        جلب بيانات مؤشر سوقي محدد

        المعطيات:
            symbol: رمز المؤشر (مثل "EGX30")

        المخرجات:
            tuple من (السعر, نسبة_التغيير) أو (None, None) عند الفشل
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """
        التحقق من أن مصدر البيانات متاح ويعمل بشكل صحيح

        المخرجات:
            True إذا كان المصدر متاحاً، False خلاف ذلك
        """
        ...


# ══════════════════════════════════════════════════════════════════════════════
# فئة مصدر بيانات TradingView - TradingView Data Source
# ══════════════════════════════════════════════════════════════════════════════

class TradingViewSource(DataSource):
    """
    مصدر بيانات TradingView Scanner API

    يقوم بجلب بيانات أسهم البورصة المصرية من واجهة TradingView Scanner API.
    يستخدم اتصال SSL آمن مع التحقق من الشهادات عبر certifi.

    نقاط النهاية المستخدمة:
    - https://scanner.tradingview.com/egypt/scan — جلب بيانات جميع الأسهم
    - https://scanner.tradingview.com/symbol — جلب بيانات مؤشر محدد

    ملاحظات:
    - يجب تعيين Content-Type: application/json في طلبات POST
    - البيانات تعاد كمصفوفة مرتبة حسب الأعمدة المطلوبة
    - يتم إزالة بادئة "EGX:" من رموز الأسهم
    """

    # عناوين URL لواجهة TradingView
    SCANNER_URL: str = "https://scanner.tradingview.com/egypt/scan"
    """عنوان URL لمسح جميع أسهم السوق المصري"""

    SYMBOL_URL: str = "https://scanner.tradingview.com/symbol"
    """عنوان URL لجلب بيانات رمز محدد (مؤشرات)"""

    # حد أقصى لعدد المحاولات
    MAX_RETRIES: int = 3
    """عدد المحاولات القصوى عند فشل الطلب"""

    # مهلة الطلب بالثواني
    REQUEST_TIMEOUT: int = 20
    """مهلة انتظار استجابة الخادم بالثواني"""

    # عدد الأسهم المطلوب جلبها
    STOCK_RANGE: int = 500
    """عدد الأسهم المطلوب جلبها من المسح"""

    def __init__(self) -> None:
        """تهيئة مصدر بيانات TradingView مع سياق SSL آمن"""
        self._ssl_context: ssl.SSLContext = get_ssl_context()
        logger.info("تم تهيئة مصدر بيانات TradingView بسياق SSL آمن")

    @property
    def name(self) -> str:
        """اسم مصدر البيانات"""
        return "TradingView"

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        بناء عناوين HTTP الافتراضية للطلبات

        المعطيات:
            extra: عناوين إضافية لدمجها مع العناوين الافتراضية

        المخرجات:
            قاموس عناوين HTTP
        """
        headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 Chrome/121.0.0.0",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        }
        if extra:
            headers.update(extra)
        return headers

    def _fetch_url(
        self,
        url: str,
        method: str = "GET",
        body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """
        إجراء طلب HTTP مع التحقق من SSL

        تقوم هذه الدالة بإجراء طلب HTTP آمن مع:
        - استخدام سياق SSL آمن مع شهادات certifi
        - فك ضغط الاستجابة gzip تلقائياً
        - مهلة زمنية للطلب

        المعطيات:
            url: عنوان URL المطلوب
            method: طريقة HTTP (GET أو POST)
            body: محتوى الطلب (لسلاسل JSON في طلبات POST)
            headers: عناوين HTTP إضافية
            timeout: مهلة زمنية بالثواني (default: self.REQUEST_TIMEOUT)

        المخرجات:
            محتوى الاستجابة كنص

        الأخطاء:
            ConnectionError: عند فشل الاتصال بالخادم
            TimeoutError: عند انتهاء مهلة الطلب
            ValueError: عند استجابة غير صالحة
        """
        hdrs = self._build_headers(headers)
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = Request(url, data=data, headers=hdrs, method=method)
        req_timeout = timeout if timeout is not None else self.REQUEST_TIMEOUT

        try:
            with urlopen(req, timeout=req_timeout, context=self._ssl_context) as response:
                raw = response.read()

                # فك ضغط gzip إذا لزم الأمر
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)

                return raw.decode("utf-8", errors="replace")

        except HTTPError as exc:
            # أخطاء HTTP مثل 405 Method Not Allowed, 403 Forbidden, 429 Too Many Requests
            logger.error(
                "خطأ HTTP %d أثناء الاتصال بـ %s: %s",
                exc.code, url, exc.reason,
            )
            if exc.code == 405:
                raise ConnectionError(
                    f"TradingView رفض الطلب (HTTP 405: Method Not Allowed). "
                    f"قد يكون الـ API قد تغيّر أو لم يعد يدعم هذا الطلب: {url}"
                ) from exc
            elif exc.code == 429:
                raise ConnectionError(
                    f"تم تجاوز حد الطلبات (HTTP 429: Too Many Requests). حاول لاحقاً: {url}"
                ) from exc
            else:
                raise ConnectionError(
                    f"خطأ HTTP {exc.code} ({exc.reason}) أثناء الاتصال بـ {url}"
                ) from exc
        except URLError as exc:
            logger.error("خطأ URL أثناء الاتصال بـ %s: %s", url, exc)
            raise ConnectionError(f"فشل الاتصال بـ {url}: {exc}") from exc
        except ssl.SSLError as exc:
            logger.error("خطأ SSL أثناء الاتصال بـ %s: %s", url, exc)
            raise ConnectionError(f"خطأ في اتصال SSL مع {url}: {exc}") from exc
        except TimeoutError as exc:
            logger.error("انتهت مهلة الاتصال بـ %s: %s", url, exc)
            raise
        except ConnectionError:
            raise
        except OSError as exc:
            logger.error("خطأ شبكة أثناء الاتصال بـ %s: %s", url, exc)
            raise ConnectionError(f"فشل الاتصال بـ {url}: {exc}") from exc

    def fetch_index(self, symbol: str = "EGX30") -> Tuple[Optional[float], Optional[float]]:
        """
        جلب بيانات مؤشر EGX30 من TradingView + Yahoo Finance كبديل

        يحاول أولاً TradingView، وإذا فشل يجرب Yahoo Finance.

        المعطيات:
            symbol: رمز المؤشر (الافتراضي: "EGX30")

        المخرجات:
            tuple من (السعر, نسبة_التغيير) أو (None, None) عند الفشل
        """
        # المحاولة الأولى: TradingView
        try:
            payload = json.dumps({
                "symbols": {"tickers": [f"EGX:{symbol}"]},
                "columns": EGX30_COLS,
            })

            response_text = self._fetch_url(
                self.SYMBOL_URL,
                method="POST",
                body=payload,
                headers={"Content-Type": "application/json"},
            )

            response_data = json.loads(response_text)
            data_list = response_data.get("data", [{}])

            if data_list:
                values = data_list[0].get("d", [None, None])
                price = values[0] if len(values) > 0 else None
                change = values[1] if len(values) > 1 else None
                if price is not None:
                    logger.info("تم جلب بيانات المؤشر %s: السعر=%.2f، التغيير=%.2f%% (TradingView)", symbol, price or 0, change or 0)
                    return price, change
        except Exception:
            logger.debug("TradingView فشل جلب المؤشر من %s — جرب Yahoo Finance", symbol)

        # المحاولة الثانية: Yahoo Finance
        try:
            import urllib.request as yf_urllib
            yahoo_symbol = "^CASE30" if symbol == "EGX30" else symbol
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}"
            yf_req = yf_urllib.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with yf_urllib.urlopen(yf_req, timeout=10) as yf_resp:
                raw = yf_resp.read()
                if yf_resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                data = json.loads(raw)
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            price = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose")
            if price and prev_close:
                change = round((price - prev_close) / prev_close * 100, 2)
                logger.info("تم جلب بيانات المؤشر %s: السعر=%.2f، التغيير=%.2f%% (Yahoo)", symbol, price, change)
                return price, change
        except Exception:
            logger.debug("Yahoo Finance فشل جلب المؤشر من %s", symbol)

        logger.error("فشل جلب المؤشر %s من جميع المصادر", symbol)
        return None, None

    def fetch_all_stocks(self) -> Dict[str, StockData]:
        """
        جلب بيانات جميع أسهم البورصة المصرية من TradingView

        يقوم بإرسال طلب POST إلى واجهة المسح للحصول على بيانات
        حتى 500 سهم مرتبة حسب القيمة السوقية. يتضمن:
        - بيانات الأسعار والمؤشرات الفنية
        - تحويل القطاعات إلى العربية
        - حساب التوصيات بناءً على Recommend.All
        - تقدير سعر الإغلاق السابق

        المخرجات:
            قاموس حيث المفتاح هو رمز السهم والقيمة هي كائن StockData

        ملاحظات:
            - يتم إزالة بادئة "EGX:" من رموز الأسهم
            - يتم تخطي الأسهم بدون سعر أو بيانات
            - يتطلب جلب EGX30 بشكل منفصل للمقارنة
        """
        # جلب EGX30 للمقارنة
        egx30_price, egx30_chg = self.fetch_index("EGX30")

        # محاولة جلب البيانات مع إعادة المحاولة عند الفشل
        last_error: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "  [%d/%d] جاري الاتصال بـ TradingView...",
                    attempt, self.MAX_RETRIES,
                )

                # بناء حمولة الطلب
                payload = json.dumps({
                    "symbols": {"query": {"types": []}},
                    "columns": COLS,
                    "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
                    "range": [0, self.STOCK_RANGE],
                })

                # إرسال الطلب
                response_text = self._fetch_url(
                    self.SCANNER_URL,
                    method="POST",
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )

                # تحليل الاستجابة
                response_data = json.loads(response_text)
                rows = response_data.get("data", [])

                # معالجة البيانات
                stocks = self._parse_stock_rows(rows, egx30_chg)

                logger.info(
                    "  تم جلب %d سهم @ %s",
                    len(stocks),
                    time.strftime("%H:%M:%S"),
                )
                return stocks

            except (json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                logger.error(
                    "  [%d/%d] خطأ في تحليل البيانات: %s",
                    attempt, self.MAX_RETRIES, exc,
                )
            except (ConnectionError, TimeoutError) as exc:
                last_error = exc
                logger.error(
                    "  [%d/%d] خطأ في الاتصال: %s",
                    attempt, self.MAX_RETRIES, exc,
                )
            except Exception as exc:
                last_error = exc
                logger.error(
                    "  [%d/%d] خطأ غير متوقع: %s",
                    attempt, self.MAX_RETRIES, exc,
                )

            # انتظار قبل إعادة المحاولة (مع زيادة تدريجية)
            if attempt < self.MAX_RETRIES:
                wait_seconds = attempt * 3
                logger.info("  إعادة المحاولة بعد %ds...", wait_seconds)
                time.sleep(wait_seconds)

        # فشلت جميع المحاولات
        logger.error(
            "فشلت جميع محاولات جلب البيانات من TradingView: %s",
            last_error,
        )
        return {}

    def _parse_stock_rows(
        self,
        rows: List[Dict[str, Any]],
        egx30_chg: Optional[float] = None,
    ) -> Dict[str, StockData]:
        """
        تحليل صفوف بيانات الأسهم من استجابة TradingView

        تقوم هذه الدالة بتحويل البيانات الخام من واجهة المسح إلى كائنات
        StockData منظمة مع:
        - تحويل أسماء القطاعات إلى العربية
        - حساب التوصيات من Recommend.All
        - تقدير سعر الإغلاق السابق
        - تقريب القيم العشرية

        المعطيات:
            rows: قائمة صفوف البيانات الخام من TradingView
            egx30_chg: نسبة تغيير مؤشر EGX30 للمقارنة

        المخرجات:
            قاموس حيث المفتاح هو رمز السهم والقيمة هي كائن StockData
        """
        stocks: Dict[str, StockData] = {}

        for row in rows:
            # استخراج رمز السهم وإزالة البادئة
            symbol = row.get("s", "").replace("EGX:", "").strip()
            data = row.get("d", [])

            # تخطي الأسهم بدون رمز أو بيانات أو سعر
            if not symbol or not data or len(data) == 0 or data[0] is None:
                continue

            # دالة مساعدة للوصول الآمن للبيانات
            def get_value(index: int, default: Any = None) -> Any:
                """الحصول على قيمة من مصفوفة البيانات بأمان"""
                return data[index] if len(data) > index else default

            # حساب التوصية من Recommend.All (العمود 15)
            rec_raw = get_value(15)
            rating = self._calculate_rating(rec_raw)

            # تحويل القطاع إلى العربية
            sector_en = get_value(17, "")
            sector_ar = SECTOR_AR.get(sector_en or "", sector_en or "أخرى")

            # تقدير سعر الإغلاق السابق من السعر والتغيير
            price_val = get_value(0)
            change_val = get_value(1)
            price_prev = None
            if price_val and change_val is not None:
                try:
                    price_prev = round(price_val / (1 + change_val / 100), 3)
                except (ZeroDivisionError, TypeError):
                    price_prev = None

            # استخراج الاسم الإنجليزي قبل بناء الكائن (للإفلات من اسم TV الفارغ)
            _name_en = get_value(12, symbol)
            # بناء كائن بيانات السهم
            stock = StockData(
                symbol=symbol,
                price=get_value(0),
                change_pct=round(get_value(1), 2) if get_value(1) is not None else None,
                change_abs=get_value(2),
                day_high=get_value(3),
                day_low=get_value(4),
                volume=get_value(5),
                market_cap=get_value(6),
                pe=get_value(7),
                avg_vol=get_value(8),
                high52w=get_value(9),
                low52w=get_value(10),
                open_p=get_value(11),
                name_en=_name_en,
                eps=get_value(13),  # earnings_per_share_basic_ttm
                rsi=round(get_value(14), 1) if get_value(14) is not None else None,
                rating=rating,
                rec_raw=rec_raw,
                div_yield=get_value(16),
                sector_en=sector_en,
                sector=sector_ar,
                industry=get_value(18),
                tv_name=EGX_ARABIC_NAMES.get(symbol) or _name_en or symbol,
                macd=get_value(20),
                macd_signal=get_value(21),
                stoch_k=get_value(22),
                stoch_d=get_value(23),
                adx=get_value(24),
                atr=get_value(25),
                bb_upper=get_value(26),
                bb_lower=get_value(27),
                bb_basis=get_value(28),
                rel_vol=get_value(29),
                sma20=get_value(30),
                sma50=get_value(31),
                sma200=get_value(32),
                ema20=get_value(33),
                ema50=get_value(34),
                perf_w=get_value(35),
                perf_1m=get_value(36),
                perf_3m=get_value(37),
                perf_6m=get_value(38),
                perf_y=get_value(39),
                high1m=get_value(40),
                low1m=get_value(41),
                high3m=get_value(42),
                low3m=get_value(43),
                rsi_prev=get_value(44),
                macd_prev=get_value(45),
                chg_from_open=get_value(46),
                price_prev=price_prev,
                egx30_chg=egx30_chg,
                source=self.name,
            )

            stocks[symbol] = stock

        return stocks

    @staticmethod
    def _calculate_rating(rec_raw: Optional[float]) -> Optional[str]:
        """
        حساب التوصية من قيمة Recommend.All

        تقوم هذه الدالة بتحويل القيمة الرقمية للتوصية إلى نص عربي
        وفقاً للجدول التالي:
        - >= 0.5: شراء قوي
        - >= 0.1: شراء
        - > -0.1: محايد
        - > -0.5: بيع
        - <= -0.5: بيع قوي

        المعطيات:
            rec_raw: القيمة الرقمية للتوصية من TradingView

        المخرجات:
            نص التوصية بالعربية أو None إذا لم تتوفر القيمة
        """
        if rec_raw is None:
            return None
        if rec_raw >= 0.5:
            return "شراء قوي"
        if rec_raw >= 0.1:
            return "شراء"
        if rec_raw > -0.1:
            return "محايد"
        if rec_raw > -0.5:
            return "بيع"
        return "بيع قوي"

    def health_check(self) -> bool:
        """
        التحقق من أن واجهة TradingView متاحة

        تقوم بمحاولة جلب بيانات EGX30 كاختبار للاتصال.

        المخرجات:
            True إذا كان المصدر متاحاً، False خلاف ذلك
        """
        try:
            price, _ = self.fetch_index("EGX30")
            is_healthy = price is not None
            if is_healthy:
                logger.info("فحص صحة TradingView: متاح (EGX30=%.2f)", price)
            else:
                logger.warning("فحص صحة TradingView: غير متاح (لم يتم الحصول على سعر)")
            return is_healthy
        except Exception as exc:
            logger.error("فحص صحة TradingView: فشل - %s", exc)
            return False


# ══════════════════════════════════════════════════════════════════════════════
# فئة إدارة البيانات - Data Manager
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    """
    عنصر التخزين المؤقت - يحتوي على البيانات ووقت التخزين

    يُستخدم لتخزين البيانات مع تتبع وقت الإنشاء لحساب صلاحية
    التخزين المؤقت.
    """
    data: Dict[str, StockData] = field(default_factory=dict)
    timestamp: float = 0.0

    @property
    def age(self) -> float:
        """عمر البيانات المخزنة بالثواني"""
        return time.time() - self.timestamp

    def is_expired(self, ttl: float) -> bool:
        """
        التحقق من انتهاء صلاحية البيانات

        المعطيات:
            ttl: مدة الصلاحية بالثواني

        المخرجات:
            True إذا انتهت الصلاحية، False خلاف ذلك
        """
        return self.age >= ttl


class DataManager:
    """
    مدير البيانات - يتحكم في جلب البيانات والتخزين المؤقت وتبديل المصادر

    يوفر هذه الفئة طبقة إدارة مركزية للبيانات تتضمن:
    - تخزين مؤقت مع مدة صلاحية قابلة للتكوين (TTL)
    - تبديل مصادر البيانات (TradingView، Yahoo Finance مستقبلاً)
    - إعادة تعيين التخزين المؤقت
    - جلب بيانات EGX30 بشكل منفصل
    - حالة السوق

    مثال الاستخدام:
        manager = DataManager(ttl=120)
        stocks = manager.get_stocks()  # يجلب البيانات مع التخزين المؤقت
        manager.reset_cache()           # إعادة تعيين التخزين المؤقت
        manager.switch_source("yahoo")  # تبديل المصدر (مستقبلاً)
    """

    # المصادر المتاحة
    SOURCES: Dict[str, type] = {
        "tradingview": TradingViewSource,
    }
    """قاموس مصادر البيانات المتاحة (مفتاح: اسم المصدر، قيمة: الفئة)"""

    def __init__(self, ttl: float = 120.0, default_source: str = "tradingview") -> None:
        """
        تهيئة مدير البيانات

        المعطيات:
            ttl: مدة صلاحية التخزين المؤقت بالثواني (الافتراضي: 120 ثانية)
            default_source: اسم مصدر البيانات الافتراضي (الافتراضي: "tradingview")

        الأخطاء:
            ValueError: إذا كان اسم المصدر غير معروف
        """
        if default_source not in self.SOURCES:
            raise ValueError(
                f"مصدر بيانات غير معروف: '{default_source}'. "
                f"المصادر المتاحة: {list(self.SOURCES.keys())}"
            )

        self._ttl: float = ttl
        """مدة صلاحية التخزين المؤقت بالثواني"""

        self._source_name: str = default_source
        """اسم مصدر البيانات الحالي"""

        self._source: DataSource = self.SOURCES[default_source]()
        """مصدر البيانات الحالي"""

        # تخزين مؤقت لبيانات الأسهم
        self._cache: CacheEntry = CacheEntry()
        """عنصر التخزين المؤقت لبيانات الأسهم"""

        # تخزين مؤقت لبيانات EGX30
        self._egx30_cache: Tuple[Optional[float], Optional[float]] = (None, None)
        """بيانات EGX30 المخزنة مؤقتاً (السعر، التغيير)"""

        self._egx30_timestamp: float = 0.0
        """وقت تخزين EGX30 مؤقتاً"""

        logger.info(
            "تم تهيئة مدير البيانات (المصدر: %s، TTL: %.0f ثانية)",
            default_source, ttl,
        )

    @property
    def ttl(self) -> float:
        """مدة صلاحية التخزين المؤقت بالثواني"""
        return self._ttl

    @ttl.setter
    def ttl(self, value: float) -> None:
        """
        تعيين مدة صلاحية التخزين المؤقت

        المعطيات:
            value: المدة بالثواني (يجب أن تكون موجبة)

        الأخطاء:
            ValueError: إذا كانت القيمة غير موجبة
        """
        if value <= 0:
            raise ValueError("مدة الصلاحية يجب أن تكون موجبة")
        self._ttl = value
        logger.info("تم تحديث مدة الصلاحية إلى %.0f ثانية", value)

    @property
    def source_name(self) -> str:
        """اسم مصدر البيانات الحالي"""
        return self._source_name

    @property
    def source(self) -> DataSource:
        """مصدر البيانات الحالي"""
        return self._source

    @property
    def is_cache_valid(self) -> bool:
        """التحقق من صلاحية التخزين المؤقت الحالي"""
        return bool(self._cache.data) and not self._cache.is_expired(self._ttl)

    @property
    def cache_age(self) -> float:
        """عمر التخزين المؤقت الحالي بالثواني"""
        return self._cache.age

    @property
    def cached_stock_count(self) -> int:
        """عدد الأسهم المخزنة مؤقتاً"""
        return len(self._cache.data)

    def switch_source(self, source_name: str) -> None:
        """
        تبديل مصدر البيانات

        تقوم هذه الدالة بتبديل مصدر البيانات الحالي ومسح التخزين المؤقت.

        المعطيات:
            source_name: اسم المصدر الجديد

        الأخطاء:
            ValueError: إذا كان اسم المصدر غير معروف
        """
        if source_name not in self.SOURCES:
            raise ValueError(
                f"مصدر بيانات غير معروف: '{source_name}'. "
                f"المصادر المتاحة: {list(self.SOURCES.keys())}"
            )

        if source_name == self._source_name:
            logger.info("مصدر البيانات المطلوب هو نفسه الحالي: %s", source_name)
            return

        # تبديل المصدر
        self._source_name = source_name
        self._source = self.SOURCES[source_name]()

        # مسح التخزين المؤقت لضمان جلب بيانات من المصدر الجديد
        self.reset_cache()

        logger.info("تم تبديل مصدر البيانات إلى: %s", source_name)

    def get_stocks(self, force_refresh: bool = False) -> Dict[str, StockData]:
        """
        الحصول على بيانات جميع الأسهم مع التخزين المؤقت

        تقوم هذه الدالة بإرجاع البيانات المخزنة مؤقتاً إذا كانت صالحة،
        أو جلب بيانات جديدة من المصدر إذا انتهت الصلاحية.

        المعطيات:
            force_refresh: تجاهل التخزين المؤقت وجلب بيانات جديدة

        المخرجات:
            قاموس حيث المفتاح هو رمز السهم والقيمة هي كائن StockData
        """
        # إرجاع البيانات المخزنة إذا كانت صالحة
        if not force_refresh and self.is_cache_valid:
            logger.debug(
                "استخدام البيانات المخزنة مؤقتاً (%d سهم، عمر: %.0f ثانية)",
                len(self._cache.data), self._cache.age,
            )
            return self._cache.data

        # جلب بيانات جديدة
        logger.info("جاري جلب بيانات جديدة من %s...", self._source_name)
        try:
            stocks = self._source.fetch_all_stocks()

            if stocks:
                # تحديث التخزين المؤقت
                self._cache = CacheEntry(data=stocks, timestamp=time.time())
                logger.info(
                    "تم تحديث التخزين المؤقت بـ %d سهم", len(stocks),
                )
            else:
                # فشل الجلب - استخدام البيانات القديمة إذا كانت متوفرة
                if self._cache.data:
                    logger.warning(
                        "فشل جلب البيانات - استخدام التخزين المؤقت القديم (%d سهم)",
                        len(self._cache.data),
                    )
                else:
                    logger.error("فشل جلب البيانات ولا يوجد تخزين مؤقت")

            return self._cache.data

        except Exception as exc:
            logger.error("خطأ أثناء جلب البيانات: %s", exc)
            # إرجاع البيانات القديمة إذا كانت متوفرة
            if self._cache.data:
                logger.warning("إرجاع التخزين المؤقت القديم بسبب الخطأ")
                return self._cache.data
            return {}

    def get_egx30(self, force_refresh: bool = False) -> Tuple[Optional[float], Optional[float]]:
        """
        الحصول على بيانات مؤشر EGX30 مع التخزين المؤقت

        المعطيات:
            force_refresh: تجاهل التخزين المؤقت وجلب بيانات جديدة

        المخرجات:
            tuple من (السعر, نسبة_التغيير) أو (None, None) عند الفشل
        """
        # التحقق من صلاحية التخزين المؤقت لـ EGX30
        if not force_refresh and self._egx30_cache[0] is not None:
            egx30_age = time.time() - self._egx30_timestamp
            if egx30_age < self._ttl:
                return self._egx30_cache

        # جلب بيانات جديدة
        try:
            price, change = self._source.fetch_index("EGX30")
            if price is not None:
                self._egx30_cache = (price, change)
                self._egx30_timestamp = time.time()
            return price, change
        except Exception as exc:
            logger.error("خطأ أثناء جلب بيانات EGX30: %s", exc)
            return self._egx30_cache

    def get_stock(self, symbol: str) -> Optional[StockData]:
        """
        الحصول على بيانات سهم محدد

        المعطيات:
            symbol: رمز السهم

        المخرجات:
            كائن StockData أو None إذا لم يتم العثور على السهم
        """
        stocks = self.get_stocks()
        return stocks.get(symbol)

    def reset_cache(self) -> None:
        """
        إعادة تعيين التخزين المؤقت

        تقوم بمسح جميع البيانات المخزنة مؤقتاً مما يضمن
        جلب بيانات جديدة في الطلب التالي.
        """
        self._cache = CacheEntry()
        self._egx30_cache = (None, None)
        self._egx30_timestamp = 0.0
        logger.info("تم إعادة تعيين التخزين المؤقت")

    def get_market_status(self) -> Tuple[str, str]:
        """
        الحصول على حالة السوق الحالية

        المخرجات:
            tuple من (نص_عربي, رمز_إنجليزي)
        """
        return market_status()

    def is_market_open(self) -> bool:
        """
        التحقق مما إذا كان السوق مفتوحاً

        المخرجات:
            True إذا كان السوق مفتوحاً، False خلاف ذلك
        """
        return is_trading_hours()

    def health_check(self) -> Dict[str, Any]:
        """
        فحص صحة مدير البيانات ومصدر البيانات

        المخرجات:
            قاموس يحتوي على حالة الصحة ومعلومات التشخيص
        """
        source_healthy = self._source.health_check()
        status_ar, status_en = market_status()

        return {
            "source": self._source_name,
            "source_healthy": source_healthy,
            "cache_valid": self.is_cache_valid,
            "cache_age_seconds": round(self.cache_age, 1),
            "cached_stocks": self.cached_stock_count,
            "ttl_seconds": self._ttl,
            "market_status": status_en,
            "market_status_ar": status_ar,
            "is_market_open": is_trading_hours(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# مثيل مدير البيانات الافتراضي - Default Data Manager Instance
# ══════════════════════════════════════════════════════════════════════════════

# مثيل مدير البيانات العالمي مع مدة صلاحية افتراضية 120 ثانية
# يمكن استخدامه مباشرة من باقي أجزاء التطبيق
data_manager = DataManager(ttl=120.0, default_source="tradingview")
"""
مثيل مدير البيانات الافتراضي

يُستخدم هذا المثيل كنقطة دخول رئيسية لجلب البيانات
من باقي أجزاء التطبيق دون الحاجة لإنشاء مثيل جديد.

مثال:
        stocks = data_manager.get_stocks()
"""


# ══════════════════════════════════════════════════════════════════════════════
# Technical Analysis Module - وحدة التحليل الفني
# ══════════════════════════════════════════════════════════════════════════════

"""
EGX Analyzer v2 — وحدة التحليل الفني
محلل البورصة المصرية — جميع دوال التحليل الفني

تحسينات عن النسخة الأصلية:
- إضافة Type Hints لجميع الدوال
- استخدام logging بدلاً من print
- حذف الدالة المكررة detect_candle_pattern
- معالجة أخطاء محسّنة
- استخدام datetime/timedelta بشكل صحيح
"""


import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# أنواع مخصصة لتوضيح البيانات
# ────────────────────────────────────────────────────────────
FibDict = Dict[str, float]
PivotDict = Dict[str, float]
MultiFibDict = Dict[str, Any]
CandlePattern = Dict[str, str]
DivergenceItem = Dict[str, Any]
ConfirmationDict = Dict[str, Any]
TradeDict = Dict[str, Any]
TrailingStopDict = Dict[str, Any]
ResistanceDict = Dict[str, Any]
PositionDict = Dict[str, Any]
AnalysisResult = Dict[str, Any]


# ════════════════════════════════════════════════════════════
# 1. مستويات فيبوناتشي
# ════════════════════════════════════════════════════════════
def calc_fibonacci(high: float, low: float) -> FibDict:
    """حساب مستويات فيبوناتشي الارتدادية"""
    diff = high - low
    if diff <= 0:
        diff = high * 0.01
    return {
        "R3":   round(high + diff * 0.618, 3),
        "R2":   round(high + diff * 0.382, 3),
        "R1":   round(high + diff * 0.236, 3),
        "P":    round((high + low) / 2,    3),
        "F236": round(high - diff * 0.236, 3),
        "F382": round(high - diff * 0.382, 3),
        "F500": round(high - diff * 0.500, 3),
        "F618": round(high - diff * 0.618, 3),
        "F786": round(high - diff * 0.786, 3),
    }


# ════════════════════════════════════════════════════════════
# 2. فيبوناتشي متعدد الأطر الزمنية
# ════════════════════════════════════════════════════════════
def calc_multi_fib(
    price: float,
    high52: Optional[float],
    low52: Optional[float],
    high3m: Optional[float],
    low3m: Optional[float],
    day_high: Optional[float],
    day_low: Optional[float],
) -> MultiFibDict:
    """
    فيبوناتشي على 3 أطر زمنية + تحديد مستويات التقاطع (confluence)
    المستويات المتقاطعة أكثر قوة من المستويات المنفردة
    """
    fib_y  = calc_fibonacci(high52,  low52)   if high52  and low52  else {}
    fib_3m = calc_fibonacci(high3m,  low3m)   if high3m  and low3m  else {}
    fib_d  = calc_fibonacci(day_high, day_low) if day_high and day_low else {}

    # إيجاد مستويات التقاطع: كل مستوى في إطار يقترب من مستوى في إطار آخر بـ 0.5%
    all_levels: List[Dict[str, Any]] = []
    for frame, fib in [("Y", fib_y), ("3M", fib_3m), ("D", fib_d)]:
        for name, val in fib.items():
            if val and val > 0:
                all_levels.append({"frame": frame, "name": name, "val": val})

    confluence: List[Dict[str, Any]] = []
    used: set = set()
    for i, a in enumerate(all_levels):
        if i in used:
            continue
        group = [a]
        for j, b in enumerate(all_levels):
            if j <= i or j in used:
                continue
            if abs(a["val"] - b["val"]) / max(a["val"], 0.001) < 0.005:
                group.append(b)
                used.add(j)
        if len(group) >= 2:
            avg_val = round(sum(x["val"] for x in group) / len(group), 3)
            frames  = "+".join(x["frame"] for x in group)
            confluence.append({
                "val": avg_val,
                "frames": frames,
                "strength": len(group),
                "name": group[0]["name"],
            })
        used.add(i)

    confluence.sort(key=lambda x: abs(x["val"] - price))

    return {
        "yearly":     fib_y,
        "quarterly":  fib_3m,
        "daily":      fib_d,
        "confluence": confluence[:6],  # أقوى 6 مستويات تقاطع
    }


# ════════════════════════════════════════════════════════════
# 3. نقاط البايفوت
# ════════════════════════════════════════════════════════════
def calc_pivot_points(high: float, low: float, close: float) -> PivotDict:
    """حساب نقاط البايفوت الكلاسيكية"""
    P = (high + low + close) / 3
    return {
        "PP": round(P, 3),
        "R1": round(2 * P - low,        3),
        "R2": round(P + (high - low),    3),
        "R3": round(high + 2 * (P - low), 3),
        "S1": round(2 * P - high,        3),
        "S2": round(P - (high - low),    3),
        "S3": round(low - 2 * (high - P), 3),
    }


# ════════════════════════════════════════════════════════════
# 4. تقييم السيولة (3 محاور)
# ════════════════════════════════════════════════════════════
def calc_liquidity_score(
    volume: Optional[float],
    avg_vol: Optional[float],
    market_cap: Optional[float],
    atr: Optional[float],
    price: Optional[float],
) -> Tuple[int, str, float]:
    """
    تقييم السيولة على 3 محاور:
    1. حجم التداول مقارنة بالمعدل
    2. قيمة التداول بالجنيه
    3. الانزلاق السعري (Slippage) بناءً على ATR
    يُرجع: (الدرجة، التصنيف، نسبة الانزلاق)
    """
    if not volume or not price:
        return 0, "بيانات غير كافية", 0.0

    # ── محور 1: نسبة الحجم ──
    rel_v = (volume / avg_vol) if avg_vol and avg_vol > 0 else 1.0
    if   rel_v >= 3.0: vol_pts = 40
    elif rel_v >= 2.0: vol_pts = 32
    elif rel_v >= 1.5: vol_pts = 24
    elif rel_v >= 1.0: vol_pts = 16
    elif rel_v >= 0.5: vol_pts = 8
    else:              vol_pts = 2

    # ── محور 2: قيمة التداول ──
    traded_egp = volume * price
    if   traded_egp >= 50_000_000: liq_pts = 40
    elif traded_egp >= 20_000_000: liq_pts = 32
    elif traded_egp >= 5_000_000:  liq_pts = 22
    elif traded_egp >= 1_000_000:  liq_pts = 12
    elif traded_egp >= 200_000:    liq_pts = 5
    else:                          liq_pts = 0

    # ── محور 3: الانزلاق السعري ──
    slip_pts = 20
    if atr and price > 0:
        sr = atr / price
        if   sr > 0.08:  slip_pts = 2
        elif sr > 0.05:  slip_pts = 6
        elif sr > 0.03:  slip_pts = 10
        elif sr > 0.015: slip_pts = 15

    total = vol_pts + liq_pts + slip_pts
    if   total >= 80: label = "سيولة ممتازة 💧💧💧"
    elif total >= 60: label = "سيولة جيدة 💧💧"
    elif total >= 40: label = "سيولة متوسطة 💧"
    elif total >= 20: label = "سيولة ضعيفة ⚠️"
    else:             label = "سيولة خطرة 🚫"

    slip_pct = round((atr / price * 0.5 * 100), 2) if atr and price > 0 else 0.0
    return total, label, slip_pct


# ════════════════════════════════════════════════════════════
# 5. نقاط الزخم المحسّنة مع ADX
# ════════════════════════════════════════════════════════════
def score_momentum(
    rsi: Optional[float],
    rsi_prev: Optional[float],
    macd: Optional[float],
    macd_signal: Optional[float],
    macd_prev: Optional[float],
    stoch_k: Optional[float],
    stoch_d: Optional[float],
    adx: Optional[float],
    rec: Optional[float],
) -> int:
    """
    نقاط الزخم المحسّنة مع ADX وزخم RSI/MACD
    ADX > 25 = ترند قوي، < 20 = لا ترند (الإشارة أضعف)
    """
    score = 50

    # ── قوة الترند بالـ ADX (معامل تعديل) ──
    # لو ADX منخفض، الإشارات الأخرى تكون أضعف
    if adx is not None:
        if   adx >= 40: adx_mult = 1.20   # ترند قوي جداً
        elif adx >= 25: adx_mult = 1.10   # ترند واضح
        elif adx >= 15: adx_mult = 0.90   # ترند ضعيف
        else:           adx_mult = 0.75   # لا يوجد ترند واضح
    else:
        adx_mult = 1.0

    # ── RSI مع زخم (هل RSI صاعد أم هابط؟) ──
    if rsi is not None:
        rsi_pts = 0
        if   rsi < 30:  rsi_pts = 18
        elif rsi < 40:  rsi_pts = 10
        elif rsi > 70:  rsi_pts = -18
        elif rsi > 60:  rsi_pts = -8
        elif 45 <= rsi <= 55: rsi_pts = 3
        # زخم RSI: هل RSI بيصعد؟
        if rsi_prev is not None:
            momentum = rsi - rsi_prev
            if momentum > 3:    rsi_pts += 5   # RSI صاعد بقوة
            elif momentum > 0:  rsi_pts += 2
            elif momentum < -3: rsi_pts -= 5
        score += rsi_pts

    # ── MACD مع زخم ──
    if macd is not None and macd_signal is not None:
        diff = macd - macd_signal
        macd_pts = min(12, abs(diff) * 100) * (1 if diff > 0 else -1)
        # هل الـ histogram يتوسع؟ (زخم إيجابي)
        if macd_prev is not None:
            prev_diff = macd_prev - macd_signal
            if diff > prev_diff:    macd_pts += 3   # histogram يتوسع
            elif diff < prev_diff:  macd_pts -= 3
        score += macd_pts

    # ── Stochastic ──
    if stoch_k is not None and stoch_d is not None:
        if   stoch_k < 20 and stoch_k > stoch_d:  score += 12
        elif stoch_k > 80 and stoch_k < stoch_d:  score -= 12
        elif stoch_k > stoch_d:                    score += 5
        else:                                       score -= 5

    # ── TradingView Recommendation ──
    if rec is not None:
        score += rec * 15

    # تطبيق معامل ADX
    deviation = score - 50
    score = 50 + deviation * adx_mult

    return max(0, min(100, round(score)))


# ════════════════════════════════════════════════════════════
# 6. تصنيف الإشارة
# ════════════════════════════════════════════════════════════
def classify_signal(
    score: int,
    rsi: Optional[float],
    price: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float],
    bb_upper: Optional[float],
    bb_lower: Optional[float],
    bb_basis: Optional[float],
    adx: Optional[float],
) -> Tuple[str, str, str, str]:
    """
    تصنيف الإشارة بناءً على الدرجة والمؤشرات
    يُرجع: (التصنيف، اللون، الإيموجي، نوع الإشارة)
    """
    bb_pos = None
    if bb_upper and bb_lower and price:
        bw = bb_upper - bb_lower
        if bw > 0:
            bp = (price - bb_lower) / bw
            bb_pos = "below_lower" if bp < 0.2 else "above_upper" if bp > 0.8 else "middle"

    trend_score = 0
    if price and sma20:  trend_score += 1 if price > sma20  else -1
    if price and sma50:  trend_score += 1 if price > sma50  else -1
    if price and sma200: trend_score += 1 if price > sma200 else -1

    # ADX يؤثر على تصنيف الإشارة: ترند ضعيف = نزل درجة
    adx_weak = adx is not None and adx < 18

    if score >= 70:
        if bb_pos == "below_lower" or (rsi and rsi < 35):
            if adx_weak: return "شراء",      "#69f0ae", "📈", "BUY"
            return              "شراء قوي",  "#00e676", "🚀", "BUY_STRONG"
        return "شراء", "#69f0ae", "📈", "BUY"
    elif score >= 55:
        if trend_score >= 1:
            return "تجميع", "#ffeb3b", "📦", "ACCUMULATE"
        return "مراقبة", "#81d4fa", "👀", "WATCH"
    elif score >= 40:
        return "انتظار", "#b0bec5", "⏳", "WAIT"
    elif score >= 25:
        return "تجنب",   "#ff8a65", "⚠️", "AVOID"
    else:
        if bb_pos == "above_upper" or (rsi and rsi > 75):
            if adx_weak: return "بيع",       "#ff5252", "⬇️", "SELL"
            return              "بيع قوي",   "#ff1744", "📉", "SELL_STRONG"
        return "بيع", "#ff5252", "⬇️", "SELL"


# ════════════════════════════════════════════════════════════
# 7. أهداف الدخول والخروج
# ════════════════════════════════════════════════════════════
def calc_entry_targets(
    price: float,
    fib: FibDict,
    pivots: PivotDict,
    signal_type: str,
    atr: Optional[float],
    volume: Optional[float] = None,
    avg_vol: Optional[float] = None,
    market_cap: Optional[float] = None,
) -> TradeDict:
    """
    حساب أهداف الدخول والخروج مع سيناريوهات مختلفة
    يدعم: شراء قوي / شراء / تجميع / بيع قوي / بيع / انتظار
    """
    liq_score, liq_label, slip_pct = calc_liquidity_score(
        volume, avg_vol, market_cap, atr, price)

    if   liq_score >= 80: liq_sl_mult = 1.000
    elif liq_score >= 60: liq_sl_mult = 1.005
    elif liq_score >= 40: liq_sl_mult = 1.010
    elif liq_score >= 20: liq_sl_mult = 1.020
    else:                 liq_sl_mult = 1.030

    if signal_type in ("BUY_STRONG", "BUY", "ACCUMULATE"):
        # ── الدعم الأقرب تحت السعر ──
        support_candidates = [fib.get("F236", 0), pivots.get("S1", 0)]
        valid_supports = [c for c in support_candidates if 0 < c < price]
        nearest_support = round(max(valid_supports), 3) if valid_supports \
                          else round(price * 0.97, 3)

        # ── تحديد entry_ideal حسب موضع السعر ──
        # حساب المسافة بين السعر وأقرب دعم كنسبة
        dist_to_support = (price - nearest_support) / price * 100 if price > 0 else 10

        if dist_to_support <= 1.5:
            # السعر على الدعم مباشرة — ادخل بسعر السوق
            entry_ideal      = round(price * 1.001, 3)
            entry_scenario   = "MARKET"
        elif dist_to_support <= 4.0:
            # السعر قريب من الدعم
            entry_ideal      = round(nearest_support * 1.005, 3)
            # ضمان: entry_ideal لا يتجاوز السعر الحالي
            if entry_ideal >= price:
                entry_ideal  = round(price * 0.999, 3)
            entry_scenario   = "NEAR"
        else:
            # السعر بعيد — استنى التراجع
            entry_ideal      = round(nearest_support, 3)
            entry_scenario   = "WAIT"

        # ── وقف الخسارة (محسوب من entry_ideal الجديد) ──
        sl_base   = min(fib.get("F618", price * 0.9), pivots.get("S2", price * 0.9))
        stop_loss = round(sl_base * 0.99 * liq_sl_mult, 3)
        if atr:
            stop_loss = max(stop_loss, round(entry_ideal - 3.0 * atr, 3))
        stop_loss = min(stop_loss, round(entry_ideal * 0.98, 3))

        targets = [
            round(max(fib.get("R1", 0), pivots.get("R1", 0)), 3),
            round(max(fib.get("R2", 0), pivots.get("R2", 0)), 3),
            round(max(fib.get("R3", 0), pivots.get("R3", 0)), 3),
        ]
        if atr and entry_ideal > 0:
            near_targets = [
                round(entry_ideal + 1.0 * atr, 3),
                round(entry_ideal + 1.5 * atr, 3),
                round(entry_ideal + 2.5 * atr, 3),
            ]
        else:
            near_targets = [round(entry_ideal * r, 3) for r in [1.02, 1.035, 1.055]]

        # ── entry_range_high من R:R = 1.5 ──
        MIN_RR = 1.5
        t1 = targets[0]
        rr_max = (t1 + MIN_RR * stop_loss) / (1 + MIN_RR)
        entry_range_high = round(rr_max, 3)
        if entry_range_high <= entry_ideal:
            entry_range_high = round(entry_ideal * 1.015, 3)

        # ── entry_range_low: الدعم الأقوى التالي ──
        rl_raw = max(fib.get("F382", 0), pivots.get("S2", 0))
        entry_range_low = round(rl_raw, 3)
        if entry_range_low >= entry_ideal:
            entry_range_low = round(entry_ideal * 0.97, 3)

    elif signal_type in ("SELL_STRONG", "SELL"):
        candidates = [fib.get("R1", 0), pivots.get("R1", 0)]
        valid = [c for c in candidates if c >= price * 0.98]
        entry_ideal = round(min(valid), 3) if valid else round(pivots.get("R1", price * 1.03), 3)
        entry_scenario = "MARKET" if abs(entry_ideal - price) / price < 0.015 else "NEAR"

        sl_base   = max(fib.get("R3", 0), pivots.get("R3", 0))
        stop_loss = round(sl_base * 1.01 / liq_sl_mult, 3)
        if atr:
            stop_loss = min(stop_loss, round(entry_ideal + 3.0 * atr, 3))
        stop_loss = max(stop_loss, round(entry_ideal * 1.02, 3))

        targets = [
            round(min(fib.get("F382", 0), pivots.get("S1", 0)), 3),
            round(min(fib.get("F618", 0), pivots.get("S2", 0)), 3),
            round(min(fib.get("F786", 0), pivots.get("S3", 0)), 3),
        ]
        if atr and entry_ideal > 0:
            near_targets = [
                round(entry_ideal - 1.0 * atr, 3),
                round(entry_ideal - 1.5 * atr, 3),
                round(entry_ideal - 2.5 * atr, 3),
            ]
        else:
            near_targets = [round(entry_ideal * r, 3) for r in [0.98, 0.965, 0.945]]

        MIN_RR = 1.5
        t1 = targets[0]
        rr_min = (t1 + MIN_RR * stop_loss) / (1 + MIN_RR)
        entry_range_low  = round(max(rr_min, entry_ideal * 0.97), 3)
        entry_range_high = round(max(fib.get("R2", 0), pivots.get("R2", 0)), 3)
        if entry_range_high <= entry_ideal:
            entry_range_high = round(entry_ideal * 1.03, 3)
    else:
        entry_ideal      = round(fib.get("F382", price * 0.95), 3)
        entry_range_high = round(fib.get("F236", price * 0.98), 3)
        entry_range_low  = round(fib.get("F618", price * 0.90), 3)
        stop_loss        = round(fib.get("F786", price * 0.88) * 0.98, 3)
        targets          = [round(fib.get("R1", 0), 3), round(fib.get("R2", 0), 3), round(fib.get("R3", 0), 3)]
        near_targets     = []
        entry_scenario   = "WAIT"

    ready = entry_range_low <= price <= entry_range_high
    if ready:
        proximity = 100.0
    elif price > entry_range_high:
        proximity = max(0.0, 100.0 - (price - entry_range_high) / entry_range_high * 1000)
    else:
        proximity = max(0.0, 100.0 - (entry_range_low - price) / entry_range_low * 500)

    risk    = abs(entry_ideal - stop_loss)
    rewards = [abs(t - entry_ideal) for t in targets]
    rr_ratios = [round(r / risk, 2) if risk > 0 else 0.0 for r in rewards]
    rr1 = rr_ratios[0] if rr_ratios else 0

    def pct(t: float) -> float:
        return round((t - entry_ideal) / entry_ideal * 100, 2) if entry_ideal else 0.0

    near_pcts = [pct(t) for t in near_targets]
    far_pcts  = [pct(t) for t in targets]
    stop_pct  = pct(stop_loss)

    rr_pts       = min(40, rr1 * 13.3)
    liq_contrib  = liq_score * 0.3
    prox_contrib = proximity * 0.3
    trade_quality = round(rr_pts + liq_contrib + prox_contrib, 1)

    if   trade_quality >= 80: quality_label = "فرصة ممتازة ⭐⭐⭐"
    elif trade_quality >= 60: quality_label = "فرصة جيدة ⭐⭐"
    elif trade_quality >= 40: quality_label = "فرصة مقبولة ⭐"
    elif trade_quality >= 20: quality_label = "انتظر تحسن الشروط ⏳"
    else:                     quality_label = "لا تناسب الآن 🚫"

    return {
        "entry_ideal":      entry_ideal,
        "entry_range_high": entry_range_high,
        "entry_range_low":  entry_range_low,
        "stop_loss":        stop_loss,
        "stop_pct":         stop_pct,
        "targets":          targets,
        "far_pcts":         far_pcts,
        "near_targets":     near_targets,
        "near_pcts":        near_pcts,
        "rr_ratios":        rr_ratios,
        "risk_pct":         round(abs(entry_ideal - stop_loss) / entry_ideal * 100, 2) if entry_ideal else 0,
        "ready":            ready,
        "proximity":        round(proximity, 1),
        "entry_scenario":   entry_scenario,  # MARKET / NEAR / WAIT
        "liq_score":        liq_score,
        "liq_label":        liq_label,
        "slip_pct":         slip_pct,
        "trade_quality":    trade_quality,
        "quality_label":    quality_label,
        "rr1":              rr1,
    }


# ════════════════════════════════════════════════════════════
# 8. كشف أنماط الشموع (نسخة واحدة فقط — حُذف التكرار)
# ════════════════════════════════════════════════════════════
def detect_candle_pattern(
    o: Optional[float],
    h: Optional[float],
    l: Optional[float],
    c: Optional[float],
    prev_c: Optional[float] = None,
) -> Optional[CandlePattern]:
    """كشف أنماط الشموع الأساسية"""
    if not all([o, h, l, c]):
        return None
    body   = abs(c - o)
    range_ = h - l
    if range_ == 0:
        return None
    body_pct   = body / range_
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l

    patterns: List[CandlePattern] = []
    if body_pct < 0.1:
        patterns.append({"name": "دوجي 🕯", "type": "NEUTRAL", "ar": "دوجي — تردد في السوق"})
    elif lower_wick > body * 2 and upper_wick < body * 0.5 and c > o:
        patterns.append({"name": "مطرقة 🔨", "type": "BULLISH", "ar": "مطرقة — انعكاس صاعد محتمل"})
    elif upper_wick > body * 2 and lower_wick < body * 0.5 and c < o:
        patterns.append({"name": "شهاب ⭐", "type": "BEARISH", "ar": "شهاب — انعكاس هابط محتمل"})
    elif prev_c and c > o and o < prev_c and c > prev_c and body_pct > 0.6:
        patterns.append({"name": "ابتلاع صاعد 🟢", "type": "BULLISH", "ar": "ابتلاع صاعد — إشارة شراء قوية"})
    elif c > o and body_pct > 0.7:
        patterns.append({"name": "صاعدة قوية", "type": "BULLISH", "ar": "شمعة صاعدة قوية"})
    elif c < o and body_pct > 0.7:
        patterns.append({"name": "هابطة قوية", "type": "BEARISH", "ar": "شمعة هابطة قوية"})

    return patterns[0] if patterns else None


# ════════════════════════════════════════════════════════════
# 9. إشارة OBV
# ════════════════════════════════════════════════════════════
def calc_obv_signal(
    price: Optional[float],
    price_prev: Optional[float],
    volume: Optional[float],
    obv_prev: Optional[float] = None,
) -> Tuple[Optional[float], float]:
    """
    OBV (On Balance Volume) — تحليل الحجم مع السعر
    صعود السعر مع صعود OBV = تأكيد قوي
    صعود السعر مع هبوط OBV = divergence تحذيري
    """
    if not volume or not price or not price_prev:
        return None, "غير متاح"
    # حساب OBV التراكمي (نسبي)
    if price > price_prev:
        obv_delta = volume
    elif price < price_prev:
        obv_delta = -volume
    else:
        obv_delta = 0
    obv_new = (obv_prev or 0) + obv_delta
    return obv_new, obv_delta


# ════════════════════════════════════════════════════════════
# 10. كشف التباعد (Divergence)
# ════════════════════════════════════════════════════════════
def detect_divergence(
    price: Optional[float],
    price_prev: Optional[float],
    rsi: Optional[float],
    rsi_prev: Optional[float],
    macd: Optional[float],
    macd_prev: Optional[float],
) -> Optional[List[DivergenceItem]]:
    """
    كشف Divergence بين السعر والمؤشرات
    - Bullish Divergence: سعر أدنى + RSI/MACD أعلى → انعكاس صاعد محتمل
    - Bearish Divergence: سعر أعلى + RSI/MACD أدنى → انعكاس هابط محتمل
    """
    if not all([price, price_prev]):
        return None

    divergences: List[DivergenceItem] = []

    # RSI Divergence
    if rsi is not None and rsi_prev is not None:
        price_lower = price < price_prev * 0.98   # سعر أدنى بـ 2%+
        price_higher = price > price_prev * 1.02  # سعر أعلى بـ 2%+
        rsi_higher = rsi > rsi_prev + 3           # RSI أعلى بـ 3+ نقاط
        rsi_lower  = rsi < rsi_prev - 3           # RSI أدنى بـ 3+ نقاط

        if price_lower and rsi_higher:
            divergences.append({
                "type":      "BULLISH",
                "indicator": "RSI",
                "strength":  min(100, int((rsi - rsi_prev) * 5)),
                "ar":        f"تباعد صاعد RSI 🟢 — السعر هبط لكن RSI ارتفع ({rsi_prev:.0f}→{rsi:.0f})",
                "signal":    +15,   # نقاط إضافية للـ score
            })
        elif price_higher and rsi_lower:
            divergences.append({
                "type":      "BEARISH",
                "indicator": "RSI",
                "strength":  min(100, int((rsi_prev - rsi) * 5)),
                "ar":        f"تباعد هابط RSI 🔴 — السعر ارتفع لكن RSI هبط ({rsi_prev:.0f}→{rsi:.0f})",
                "signal":    -15,
            })

    # MACD Divergence
    if macd is not None and macd_prev is not None:
        price_lower  = price < price_prev * 0.98
        price_higher = price > price_prev * 1.02
        macd_higher  = macd > macd_prev * 1.1 if macd_prev != 0 else macd > 0
        macd_lower   = macd < macd_prev * 0.9 if macd_prev != 0 else macd < 0

        if price_lower and macd_higher and macd > 0:
            divergences.append({
                "type":      "BULLISH",
                "indicator": "MACD",
                "strength":  70,
                "ar":        "تباعد صاعد MACD 🟢 — تأكيد انعكاس محتمل",
                "signal":    +10,
            })
        elif price_higher and macd_lower and macd < 0:
            divergences.append({
                "type":      "BEARISH",
                "indicator": "MACD",
                "strength":  70,
                "ar":        "تباعد هابط MACD 🔴 — تحذير من انعكاس",
                "signal":    -10,
            })

    return divergences if divergences else None


# ════════════════════════════════════════════════════════════
# 11. وقف الخسارة المتحرك (Trailing Stops)
# ════════════════════════════════════════════════════════════
def calc_trailing_stops(
    entry_price: Optional[float],
    stop_loss: Optional[float],
    near_targets: List[float],
    far_targets: List[float],
    signal_type: str,
) -> List[TrailingStopDict]:
    """
    وقف الخسارة المتحرك (Trailing Stop)
    المستوى 0: الوقف الأصلي (تحت الدخول)
    المستوى 1 (near_t3):  بعد الهدف القريب 3 → الوقف لسعر الدخول (صفقة بلا خسارة)
    المستوى 2 (far_t1):   بعد الهدف البعيد 1 → الوقف للهدف القريب 3
    المستوى 3 (far_t2):   بعد الهدف البعيد 2 → الوقف للهدف البعيد 1
    """
    if not entry_price or not stop_loss:
        return []

    levels: List[TrailingStopDict] = [
        {
            "level": 0,
            "trigger": None,
            "new_stop": stop_loss,
            "ar": f"الوقف الابتدائي: {stop_loss}",
            "risk": "خسارة محتملة",
        },
    ]
    if len(near_targets) >= 3:
        levels.append({
            "level": 1,
            "trigger": near_targets[2],
            "new_stop": round(entry_price * 1.001, 3),
            "ar": f"بعد الهدف القريب 3 → حرّك الوقف لـ {round(entry_price * 1.001, 2)} (صفر خسارة) ✅",
            "risk": "صفر مخاطرة",
        })
    if len(far_targets) >= 1:
        levels.append({
            "level": 2,
            "trigger": far_targets[0],
            "new_stop": round(near_targets[2], 3) if len(near_targets) >= 3 else round(entry_price * 1.001, 3),
            "ar": f"بعد الهدف البعيد 1 → حرّك الوقف لـ {round(near_targets[2], 2) if len(near_targets) >= 3 else round(entry_price * 1.001, 2)} (الهدف القريب 3) 💰",
            "risk": "ربح مضمون",
        })
    if len(far_targets) >= 2:
        levels.append({
            "level": 3,
            "trigger": far_targets[1],
            "new_stop": round(far_targets[0], 3),
            "ar": f"بعد الهدف البعيد 2 → حرّك الوقف لـ {round(far_targets[0], 2)} (الهدف البعيد 1) 🏆",
            "risk": "ربح أكبر محمي",
        })
    return levels


# ════════════════════════════════════════════════════════════
# 12. عدّاد تأكيد الإشارات
# ════════════════════════════════════════════════════════════
def count_confirmed_signals(
    rsi: Optional[float],
    macd: Optional[float],
    macd_signal: Optional[float],
    stoch_k: Optional[float],
    stoch_d: Optional[float],
    price: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
    bb_lower: Optional[float],
    bb_upper: Optional[float],
    adx: Optional[float],
    divergences: Optional[List[DivergenceItem]],
    candle: Optional[CandlePattern],
    vol_class: Optional[str],
) -> ConfirmationDict:
    """
    عدد المؤشرات المتوافقة (Signal Confirmation)
    كل مؤشر بيعطي +1 أو -1
    المجموع الموجب = تأكيد شراء
    المجموع السالب = تأكيد بيع
    """
    bull_count = 0
    bear_count = 0
    signals: List[str] = []

    # RSI
    if rsi is not None:
        if rsi < 35:
            bull_count += 1; signals.append("RSI تشبع بيع ✓")
        elif rsi > 65:
            bear_count += 1; signals.append("RSI تشبع شراء ✓")

    # MACD تقاطع
    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0:
            bull_count += 1; signals.append("MACD تقاطع صاعد ✓")
        elif macd < macd_signal and macd < 0:
            bear_count += 1; signals.append("MACD تقاطع هابط ✓")

    # Stochastic
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 25 and stoch_k > stoch_d:
            bull_count += 1; signals.append("Stoch تقاطع صاعد من التشبع ✓")
        elif stoch_k > 75 and stoch_k < stoch_d:
            bear_count += 1; signals.append("Stoch تقاطع هابط من التشبع ✓")

    # المتوسطات
    if price and sma20 and sma50:
        if price > sma20 > sma50:
            bull_count += 1; signals.append("فوق SMA20 و SMA50 ✓")
        elif price < sma20 < sma50:
            bear_count += 1; signals.append("تحت SMA20 و SMA50 ✓")

    # بولينجر
    if bb_lower and bb_upper and price:
        bw = bb_upper - bb_lower
        if bw > 0:
            pct = (price - bb_lower) / bw
            if pct < 0.15:
                bull_count += 1; signals.append("عند الحد السفلي للبولينجر ✓")
            elif pct > 0.85:
                bear_count += 1; signals.append("عند الحد العلوي للبولينجر ✓")

    # ADX (ترند)
    if adx and adx >= 25:
        signals.append(f"ADX={adx:.0f} ترند قوي ✓")

    # Divergence
    if divergences:
        for d in divergences:
            if d["type"] == "BULLISH":
                bull_count += 1; signals.append(f"تباعد {d['indicator']} صاعد ✓")
            elif d["type"] == "BEARISH":
                bear_count += 1; signals.append(f"تباعد {d['indicator']} هابط ✓")

    # نمط الشمعة
    if candle:
        if candle["type"] == "BULLISH":
            bull_count += 1; signals.append(f"{candle['name']} ✓")
        elif candle["type"] == "BEARISH":
            bear_count += 1; signals.append(f"{candle['name']} ✓")

    # حجم
    if vol_class and ("مرتفع" in vol_class or "استثنائي" in vol_class):
        signals.append("حجم تداول مرتفع ✓")

    total = bull_count + bear_count
    if   bull_count >= 5: conf_label = "تأكيد قوي جداً 🔥"
    elif bull_count >= 4: conf_label = "تأكيد قوي ✅"
    elif bull_count >= 3: conf_label = "تأكيد جيد 👍"
    elif bull_count >= 2: conf_label = "تأكيد جزئي ⚠️"
    else:                 conf_label = "تأكيد ضعيف ❌"

    return {
        "bull_count":  bull_count,
        "bear_count":  bear_count,
        "total":       total,
        "label":       conf_label,
        "signals":     signals,
        "score_bonus": bull_count * 3 - bear_count * 3,  # نقاط إضافية للـ score
    }


# ════════════════════════════════════════════════════════════
# 13. حساب حجم الصفقة
# ════════════════════════════════════════════════════════════
def calc_position_size(
    capital: Optional[float],
    entry_price: Optional[float],
    stop_loss: Optional[float],
    risk_pct: float = 2.0,
) -> Optional[PositionDict]:
    """
    حساب حجم الصفقة المثالي بناءً على إدارة المخاطر
    القاعدة: لا تخاطر بأكثر من 2% من رأس المال في صفقة واحدة
    حجم الصفقة = (رأس المال × نسبة المخاطرة) ÷ (سعر الدخول - وقف الخسارة)
    """
    if not capital or not entry_price or not stop_loss:
        return None
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        return None
    max_risk_egp   = capital * (risk_pct / 100)
    shares         = int(max_risk_egp / risk_per_share)
    total_cost     = round(shares * entry_price, 2)
    pct_of_capital = round(total_cost / capital * 100, 1) if capital > 0 else 0
    return {
        "shares":          shares,
        "total_cost":      total_cost,
        "pct_of_capital":  pct_of_capital,
        "risk_egp":        round(shares * risk_per_share, 2),
        "risk_pct_actual": risk_pct,
        "max_risk_egp":    round(max_risk_egp, 2),
    }


# ════════════════════════════════════════════════════════════
# 14. قوة المقاومة
# ════════════════════════════════════════════════════════════
def calc_resistance_strength(
    price: float,
    high52: Optional[float],
    pivots: PivotDict,
    fib: FibDict,
) -> ResistanceDict:
    """
    قوة المقاومة القادمة — هل السهم قريب من مقاومة قوية؟
    بيحسب أقرب مستوى مقاومة وعدد المرات اللي اختبره السعر
    """
    resistances: List[Dict[str, Any]] = []
    # مستويات المقاومة من Pivot + Fibonacci
    for key, val in {**pivots, **fib}.items():
        if val and val > price * 1.005:  # مقاومة فوق السعر بـ 0.5%+
            dist_pct = round((val - price) / price * 100, 2)
            strength = 1
            # مستويات التقاطع أقوى
            for key2, val2 in {**pivots, **fib}.items():
                if key2 != key and val2 and abs(val - val2) / val < 0.005:
                    strength += 1
            resistances.append({
                "level":    round(val, 3),
                "dist_pct": dist_pct,
                "strength": strength,
                "source":   "Pivot" if key in ("R1", "R2", "R3", "PP") else "Fib",
                "key":      key,
            })

    # 52-week high مقاومة قوية
    if high52 and high52 > price * 1.005:
        resistances.append({
            "level":    high52,
            "dist_pct": round((high52 - price) / price * 100, 2),
            "strength": 3,
            "source":   "52W High",
            "key":      "H52",
        })

    # ترتيب حسب القرب
    resistances.sort(key=lambda x: x["dist_pct"])
    nearest = resistances[:3] if resistances else []

    # هل السهم قريب جداً من مقاومة قوية؟ (أقل من 3%)
    near_resistance = any(r["dist_pct"] < 3.0 and r["strength"] >= 2 for r in nearest)

    return {
        "nearest":         nearest,
        "near_resistance": near_resistance,
        "warning":         "⚠️ قريب من مقاومة قوية" if near_resistance else None,
    }


# ════════════════════════════════════════════════════════════
# 15. وقت الدخول الأمثل لسوق EGX
# ════════════════════════════════════════════════════════════
def calc_optimal_entry_time() -> str:
    """
    أفضل أوقات الدخول في البورصة المصرية
    مبني على سلوك السوق: أول 30 دقيقة وآخر 30 دقيقة الأكثر تقلباً
    التوقيت: بتوقيت القاهرة (مع DST)
    """
    now = cairo_now()
    h, m = now.hour, now.minute
    mins = h * 60 + m

    if   600 <= mins <= 630:
        return "🔥 أول 30 دقيقة — حركة قوية، ادخل بحذر"
    elif 630 <= mins <= 720:
        return "✅ وقت جيد للدخول — السوق استقر"
    elif 720 <= mins <= 810:
        return "👍 وقت مثالي — منتصف الجلسة"
    elif 810 <= mins <= 840:
        return "⏰ آخر 30 دقيقة — حركة قبل الإغلاق"
    elif mins > 840:
        return "🔒 السوق أغلق"
    else:
        return "⏳ السوق لم يفتح بعد"


# ════════════════════════════════════════════════════════════
# 16. التحليل الشامل للسهم
# ════════════════════════════════════════════════════════════
def analyze_stock(sym: str, d: Dict[str, Any]) -> Optional[AnalysisResult]:
    """
    التحليل الفني الشامل للسهم — يجمع كل الدوال السابقة
    يُرجع قاموس بكل بيانات التحليل أو None لو السعر صفر
    """
    price = d.get("price") or 0
    if not price:
        return None

    # ── استخراج البيانات مع قيم افتراضية ──
    _h = d.get("high52w"); high52   = _h if _h is not None else price * 1.1
    _l = d.get("low52w");  low52    = _l if _l is not None else price * 0.9
    _h = d.get("high3m");  high3m   = _h if _h is not None else price * 1.05
    _l = d.get("low3m");   low3m    = _l if _l is not None else price * 0.95
    _h = d.get("day_high"); day_high = _h if _h is not None else price
    _l = d.get("day_low");  day_low  = _l if _l is not None else price
    rsi      = d.get("rsi")
    rsi_prev = d.get("rsi_prev")
    macd     = d.get("macd")
    macd_sig = d.get("macd_signal")
    macd_prev = d.get("macd_prev")
    stoch_k  = d.get("stoch_k")
    stoch_d  = d.get("stoch_d")
    adx      = d.get("adx")
    atr      = d.get("atr")
    rec      = d.get("rec_raw")
    sma20    = d.get("sma20")
    sma50    = d.get("sma50")
    sma200   = d.get("sma200")
    bb_upper = d.get("bb_upper")
    bb_lower = d.get("bb_lower")
    bb_basis = d.get("bb_basis")
    volume   = d.get("volume")
    avg_vol  = d.get("avg_vol")
    open_p   = d.get("open_p")
    egx30_chg = d.get("_egx30_chg")

    # فيبوناتشي متعدد الأطر
    multi_fib = calc_multi_fib(price, high52, low52, high3m, low3m, day_high, day_low)
    fib   = multi_fib["yearly"]
    pivots = calc_pivot_points(day_high, day_low, price)

    # زخم محسّن مع ADX
    score = score_momentum(rsi, rsi_prev, macd, macd_sig, macd_prev, stoch_k, stoch_d, adx, rec)

    # إشارة
    label, color, emoji, sig_type = classify_signal(
        score, rsi, price, sma20, sma50, sma200, bb_upper, bb_lower, bb_basis, adx)

    # خطة التداول
    trade = calc_entry_targets(
        price, fib, pivots, sig_type, atr,
        volume=volume, avg_vol=avg_vol,
        market_cap=d.get("market_cap"))

    # حجم
    rel_v = (volume / avg_vol) if avg_vol and avg_vol > 0 else 1.0
    if   rel_v >= 3.0: vol_class = "استثنائي 🔥"
    elif rel_v >= 2.0: vol_class = "مرتفع جداً ⚡"
    elif rel_v >= 1.5: vol_class = "مرتفع ↑"
    elif rel_v >= 0.7: vol_class = "عادي ✓"
    else:              vol_class = "منخفض ↓"

    # المتوسطات
    ma_trend: List[str] = []
    if sma20:  ma_trend.append("فوق SMA20"  if price > sma20  else "تحت SMA20")
    if sma50:  ma_trend.append("فوق SMA50"  if price > sma50  else "تحت SMA50")
    if sma200: ma_trend.append("فوق SMA200" if price > sma200 else "تحت SMA200")

    # البولينجر
    bb_pos_pct: Optional[float] = None
    if bb_upper and bb_lower:
        bw = bb_upper - bb_lower
        if bw > 0:
            bb_pos_pct = round((price - bb_lower) / bw * 100, 1)

    # الأداء مقارنة بـ EGX30
    vs_egx30: Optional[float] = None
    stock_chg = d.get("change_pct") or 0
    if egx30_chg is not None and stock_chg is not None:
        vs_egx30 = round(stock_chg - egx30_chg, 2)

    # ADX classification
    if adx is not None:
        if   adx >= 40: adx_label = "ترند قوي جداً 💪"
        elif adx >= 25: adx_label = "ترند واضح ✓"
        elif adx >= 15: adx_label = "ترند ضعيف ⚠️"
        else:           adx_label = "لا يوجد ترند ❌"
    else:
        adx_label = "—"

    # نمط الشمعة
    candle = detect_candle_pattern(open_p, day_high, day_low, price)

    # Divergence
    _pp = d.get("price_prev"); price_prev = _pp if _pp is not None else price
    divergences = detect_divergence(price, price_prev, rsi, rsi_prev, macd, macd_prev)

    # تأكيد الإشارة بتقارب المؤشرات
    confirmation = count_confirmed_signals(
        rsi, macd, macd_sig, stoch_k, stoch_d,
        price, sma20, sma50, bb_lower, bb_upper,
        adx, divergences, candle, vol_class)

    # إضافة نقاط Divergence والتأكيد للـ score
    div_bonus  = sum(d["signal"] for d in divergences) if divergences else 0
    conf_bonus = confirmation["score_bonus"]
    score_adj  = max(0, min(100, score + div_bonus + conf_bonus))

    # إعادة تصنيف الإشارة بالـ score المحسّن
    if score_adj != score:
        label, color, emoji, sig_type = classify_signal(
            score_adj, rsi, price, sma20, sma50, sma200,
            bb_upper, bb_lower, bb_basis, adx)
        score = score_adj

    # وقف الخسارة المتحرك
    trailing_stops = calc_trailing_stops(
        trade.get("entry_ideal"),
        trade.get("stop_loss"),
        trade.get("near_targets", []),
        trade.get("targets", []),
        sig_type)

    # قوة المقاومة القادمة
    resistance_info = calc_resistance_strength(price, high52, pivots, fib)

    # Position Sizing (بدون رأس مال — يُحسب في الـ frontend)
    # نحفظ المعطيات فقط، الحساب بيتم في الـ frontend لما يدخل رأس المال
    position_data: PositionDict = {
        "entry":     trade.get("entry_ideal"),
        "stop":      trade.get("stop_loss"),
        "risk_per_share": round(abs((trade.get("entry_ideal") or price) -
                                    (trade.get("stop_loss") or price * 0.95)), 3),
    }

    # وقت الدخول الأمثل
    entry_time_hint = calc_optimal_entry_time()

    return {
        "score":            score_adj,
        "signal":           label,
        "signal_color":     color,
        "signal_emoji":     emoji,
        "signal_type":      sig_type,
        "multi_fib":        multi_fib,
        "pivots":           pivots,
        "trade":            trade,
        "adx_label":        adx_label,
        "vol_class":        vol_class,
        "ma_trend":         ma_trend,
        "bb_pos_pct":       bb_pos_pct,
        "vs_egx30":         vs_egx30,
        "candle":           candle,
        "divergences":      divergences,
        "confirmation":     confirmation,
        "trailing_stops":   trailing_stops,
        "resistance_info":  resistance_info,
        "position_data":    position_data,
        "entry_time_hint":  entry_time_hint,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Decision Engine Module - محرك القرار
# ══════════════════════════════════════════════════════════════════════════════

"""
محرك القرار التلقائي - محلل البورصة المصرية v2
Decision Engine Module - EGX Statistical Analyzer v2

هذه الوحدة تحتوي على محرك القرار التلقائي الذي يعمل في الخلفية
لتحليل الأسهم واتخاذ قرارات التداول بناءً على الإعدادات والشروط المحددة.

التحسينات عن النسخة الأصلية:
- تحويل إلى فئة DecisionEngine قابلة للبدء/الإيقاف
- استخدام threading للتنفيذ في الخلفية
- إضافة 3 أوضاع: AUTO / SEMI_AUTO / MANUAL
- إضافة حد خسارة يومي (Daily Loss Limit)
- استخدام logging بدلاً من print
- استيراد من الوحدات الأخرى (data_fetcher, technical_analysis, database)
- التعامل مع بيانات StockData المنظمة بدلاً من القواميس العادية
"""


import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ثوابت محرك القرار
# Decision Engine Constants
# ══════════════════════════════════════════════════════════════════════════════

# أقصى عدد إشارات في الذاكرة
MAX_SIGNALS_IN_MEMORY = 100

# أنواع الإجراءات
ACTION_OPEN = "OPEN"
ACTION_CLOSE_T1 = "CLOSE_T1"
ACTION_CLOSE_T2 = "CLOSE_T2"
ACTION_CLOSE_T3 = "CLOSE_T3"
ACTION_CLOSE_STOP = "CLOSE_STOP"
ACTION_TRAIL_STOP = "TRAIL_STOP"

# أنواع الإشارات المسموح بفتح صفقات عليها
BUY_SIGNALS = ("BUY_STRONG", "BUY", "ACCUMULATE")

# سيناريوهات الدخول المسموح بها
ENTRY_SCENARIOS_ALLOWED = ("MARKET", "NEAR")

# توزيع الكمية على الأهداف (30% / 30% / 40%)
Q1_RATIO = 0.10  # near_t1
Q2_RATIO = 0.15  # near_t2
Q3_RATIO = 0.25  # near_t3
Q4_RATIO = 0.30  # far_t1
Q5_RATIO = 0.20  # far_t2


# ══════════════════════════════════════════════════════════════════════════════
# دوال بناء بطاقة الإشارة
# Signal Card Builder Functions
# ══════════════════════════════════════════════════════════════════════════════

def build_signal_card(
    sym: str,
    v: Dict[str, Any],
    a: Dict[str, Any],
    t: Dict[str, Any],
    action: str,
    reason: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """
    بناء بطاقة الإشارة الكاملة (قابلة للنسخ وتنفيذها في شركة الوساطة)
    Build a complete signal card (copyable and executable at brokerage)

    المعطيات:
        sym:      رمز السهم
        v:        بيانات السهم الأساسية (السعر، المؤشرات الفنية الخام)
        a:        نتيجة التحليل (الإشارة، التأكيد، الدرجة)
        t:        بيانات التداول (أهداف، وقف خسارة، جودة)
        action:   نوع الإجراء (OPEN / CLOSE_T1 / CLOSE_T2 / CLOSE_T3 / CLOSE_STOP / TRAIL_STOP)
        reason:   سبب الإشارة
        settings: إعدادات التطبيق (رأس المال، نسبة المخاطرة)

    المخرجات:
        قاموس يحتوي على جميع تفاصيل الإشارة مع نص عربي جاهز للنسخ
    """
    # استخراج البيانات الأساسية
    price    = v.get("price", 0)
    name     = v.get("tv_name", sym)
    cap      = settings.get("capital", DEFAULT_CAPITAL)
    risk_pct = settings.get("risk_pct", DEFAULT_RISK_PCT)

    # استخراج بيانات التداول
    entry    = t.get("entry_ideal", price)
    stop     = t.get("stop_loss", price * 0.95)
    near_t   = t.get("near_targets", [])
    far_t    = t.get("targets", [])
    near_p   = t.get("near_pcts", [])
    far_p    = t.get("far_pcts", [])
    rr1      = t.get("rr1", 0)
    tq       = t.get("trade_quality", 0)
    liq      = t.get("liq_label", "")
    scen     = t.get("entry_scenario", "WAIT")
    conf     = a.get("confirmation", {})

    # ══════════════════════════════════════════════════════════════
    # حساب الكمية المثالية بناءً على إدارة المخاطر
    # ══════════════════════════════════════════════════════════════
    risk_per_share = abs(entry - stop) if entry and stop else 0.01
    max_risk_egp   = cap * risk_pct / 100
    shares         = int(max_risk_egp / risk_per_share) if risk_per_share > 0 else 0
    total_cost     = round(shares * entry, 2) if entry else 0

    # توزيع الكمية على الأهداف (10% قريب1 / 15% قريب2 / 25% قريب3 / 30% بعيد1 / 20% بعيد2)
    q_n1 = int(shares * Q1_RATIO)
    q_n2 = int(shares * Q2_RATIO)
    q_n3 = int(shares * Q3_RATIO)
    q_f1 = int(shares * Q4_RATIO)
    q_f2 = shares - q_n1 - q_n2 - q_n3 - q_f1
    q1 = q_n1
    q2 = q_n2
    q3 = q_n3 + q_f1 + q_f2

    # التوقيت الحالي
    # الوقت بتوقيت القاهرة (DST تلقائي)
    _cairo_now = cairo_now()
    now_str  = _cairo_now.strftime("%H:%M")
    date_str = _cairo_now.strftime("%Y-%m-%d")

    # ══════════════════════════════════════════════════════════════
    # بناء قاموس بطاقة الإشارة
    # ══════════════════════════════════════════════════════════════
    card: Dict[str, Any] = {
        "id":          f"{sym}_{int(time.time())}",
        "action":      action,        # OPEN / CLOSE_T1 / CLOSE_T2 / CLOSE_T3 / CLOSE_STOP / TRAIL_STOP
        "reason":      reason,
        "symbol":      sym,
        "name":        name,
        "time":        now_str,
        "date":        date_str,
        "price":       price,
        "entry":       entry,
        "stop":        stop,
        "scenario":    scen,
        "shares":      shares,
        "total_cost":  total_cost,
        "risk_egp":    round(shares * risk_per_share, 2),
        "risk_pct_cap": round(total_cost / cap * 100, 1) if cap > 0 else 0,
        "q1": q1, "q2": q2, "q3": q3,
        "q_n1": q_n1, "q_n2": q_n2, "q_n3": q_n3,
        "q_f1": q_f1, "q_f2": q_f2,
        # الأهداف القريبة
        "near_t1":     near_t[0] if len(near_t) > 0 else None,
        "near_t2":     near_t[1] if len(near_t) > 1 else None,
        "near_t3":     near_t[2] if len(near_t) > 2 else None,
        # الأهداف البعيدة
        "far_t1":      far_t[0]  if len(far_t) > 0  else None,
        "far_t2":      far_t[1]  if len(far_t) > 1  else None,
        # نسب الأهداف القريبة
        "near_p1":     near_p[0] if len(near_p) > 0 else None,
        "near_p2":     near_p[1] if len(near_p) > 1 else None,
        "near_p3":     near_p[2] if len(near_p) > 2 else None,
        # مؤشرات الجودة
        "rr1":           rr1,
        "trade_quality": round(tq, 1),
        "liq_label":     liq,
        "confirmation":  conf.get("label", ""),
        "bull_count":    conf.get("bull_count", 0),
        "signal":        a.get("signal", ""),
        "score":         a.get("score", 0),
        "adx":           v.get("adx"),
        "rsi":           v.get("rsi"),
        "sector":        v.get("sector", ""),
        "change_pct":    v.get("change_pct"),
    }

    # ══════════════════════════════════════════════════════════════
    # بناء النص العربي للبطاقة (للنسخ واللصق في شركة الوساطة)
    # ══════════════════════════════════════════════════════════════
    action_ar = {
        "OPEN":       "🚀 فتح صفقة شراء جديدة",
        "CLOSE_T1":   "🎯 جني أرباح — الهدف القريب 1",
        "CLOSE_T2":   "🎯 جني أرباح — الهدف القريب 2",
        "CLOSE_T3":   "🏆 جني أرباح — الهدف القريب 3",
        "CLOSE_FAR1": "🏆 جني أرباح — الهدف البعيد 1",
        "CLOSE_FAR2": "🏆 جني أرباح — الهدف البعيد 2",
        "CLOSE_STOP": "🛑 وقف الخسارة — اخرج الآن",
        "TRAIL_STOP": "📌 حرّك وقف الخسارة",
    }.get(action, action)

    lines = [
        f"{'━' * 36}",
        f"{action_ar}",
        f"{'━' * 36}",
        f"السهم:      {sym} — {name}",
        f"التوقيت:    {now_str} | {date_str}",
        f"السعر الحالي: {price} ج",
    ]

    if action == "OPEN":
        lines += [
            f"{'─' * 36}",
            f"سعر الدخول:  {entry} ج  ({scen})",
            f"وقف الخسارة: {stop} ج",
            f"{'─' * 36}",
            f"الكمية الكلية: {shares} سهم = {total_cost} ج",
            f"  ق1 ({q_n1} سهم) → اجني عند {near_t[0] if near_t else '—'} ج (+{near_p[0] if near_p else '—'}%) — وقف: سعر الدخول",
            f"  ق2 ({q_n2} سهم) → اجني عند {near_t[1] if len(near_t) > 1 else '—'} ج (+{near_p[1] if len(near_p) > 1 else '—'}%)",
            f"  ق3 ({q_n3} سهم) → اجني عند {near_t[2] if len(near_t) > 2 else '—'} ج (+{near_p[2] if len(near_p) > 2 else '—'}%) — وقف: سعر الدخول",
            f"  ب1 ({q_f1} سهم) → اجني عند {far_t[0] if far_t else '—'} ج (+{far_p[0] if far_p else '—'}%) — وقف: ق3",
            f"  ب2 ({q_f2} سهم) → اجني عند {far_t[1] if len(far_t) > 1 else '—'} ج (+{far_p[1] if len(far_p) > 1 else '—'}%) — وقف: ب1",
            f"{'─' * 36}",
            f"R:R الهدف 1: {rr1}x | جودة: {round(tq, 0)}/100",
            f"تأكيد: {conf.get('label', '')} ({conf.get('bull_count', 0)} مؤشر)",
            f"سيولة: {liq}",
            f"الاستثمار: {round(total_cost / cap * 100, 1) if cap else '—'}% من رأس المال",
            f"أقصى خسارة: {round(shares * risk_per_share, 0)} ج ({risk_pct}%)",
        ]
    elif action in ("CLOSE_T1", "CLOSE_T2", "CLOSE_T3"):
        tgt_idx = {"CLOSE_T1": 0, "CLOSE_T2": 1, "CLOSE_T3": 2}[action]
        qty     = [q_n1, q_n2, q_n3][tgt_idx]
        tgt_p   = near_t[tgt_idx] if tgt_idx < len(near_t) else price
        pct     = near_p[tgt_idx] if tgt_idx < len(near_p) else 0
        trail_note = ""
        if action == "CLOSE_T3":
            trail_note = "→ الوقف يتحرك لسعر الدخول"
        lines += [
            f"{'─' * 36}",
            f"اجني: {qty} سهم بسعر {tgt_p} ج",
            f"الربح: +{pct}% من الدخول",
            f"بعد التنفيذ: حرّك الوقف → {entry} ج {trail_note}",
        ]
    elif action in ("CLOSE_FAR1", "CLOSE_FAR2"):
        tgt_idx = {"CLOSE_FAR1": 0, "CLOSE_FAR2": 1}[action]
        qty     = [q_f1, q_f2][tgt_idx]
        tgt_p   = far_t[tgt_idx] if tgt_idx < len(far_t) else price
        pct     = far_p[tgt_idx] if tgt_idx < len(far_p) else 0
        trail_note = "→ الوقف يتحرك لق3" if action == "CLOSE_FAR1" else "→ الوقف يتحرك لب1 ← أغلق الصفقة"
        lines += [
            f"{'─' * 36}",
            f"اجني: {qty} سهم بسعر {tgt_p} ج",
            f"الربح: +{pct}% من الدخول",
            f"{trail_note}",
        ]
    elif action == "CLOSE_STOP":
        lines += [
            f"{'─' * 36}",
            f"اخرج من كل الكمية فوراً",
            f"السبب: {reason}",
        ]
    elif action == "TRAIL_STOP":
        lines += [
            f"{'─' * 36}",
            f"حرّك وقف الخسارة لـ: {reason}",
        ]

    lines.append(f"{'━' * 36}")
    card["text"] = "\n".join(lines)
    return card


# ══════════════════════════════════════════════════════════════════════════════
# فئة محرك القرار
# Decision Engine Class
# ══════════════════════════════════════════════════════════════════════════════
