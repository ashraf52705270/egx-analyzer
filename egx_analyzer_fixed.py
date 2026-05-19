#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محلل البورصة المصرية الإحصائي - EGX Statistical Analyzer v2
ملف واحد مكتفى ذاتياً

طرق التشغيل:
  python egx_analyzer.py              ← تشغيل عادي على بورت 8000
  python egx_analyzer.py --port 9000  ← تشغيل على بورت مختلف
  python egx_analyzer.py --debug      ← وضع التطوير

⭐ المتطلبات: Python 3.9+
   المكتبات الناقصة يتم تثبيتها تلقائياً عند أول تشغيل
"""

# ══════════════════════════════════════════════════════════════════════════════
# تثبيت تلقائي للمكتبات الناقصة - Auto-install missing dependencies
# ══════════════════════════════════════════════════════════════════════════════
import subprocess
import sys

REQUIRED_PACKAGES = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "sqlalchemy>=2.0.0",
    "pyjwt>=2.8.0",
    "cryptography>=41.0.0",
    "bcrypt>=4.1.0",
    "certifi>=2023.0.0",
    "python-multipart>=0.0.6",
    "pydantic>=2.0.0",
]

def _install_missing():
    """تثبيت المكتبات الناقصة تلقائياً"""
    import importlib
    missing = []
    check_imports = {
        "fastapi": "fastapi>=0.104.0",
        "uvicorn": "uvicorn[standard]>=0.24.0",
        "sqlalchemy": "sqlalchemy>=2.0.0",
        "jwt": "pyjwt>=2.8.0",
        "cryptography": "cryptography>=41.0.0",
        "bcrypt": "bcrypt>=4.1.0",
        "certifi": "certifi>=2023.0.0",
        "multipart": "python-multipart>=0.0.6",
        "pydantic": "pydantic>=2.0.0",
    }
    for mod, pkg in check_imports.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("📦 جاري تثبيت المكتبات الناقصة...")
        for pkg in missing:
            print(f"   ⬇️  {pkg}")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--break-system-packages"] + missing,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print("✅ تم تثبيت جميع المكتبات بنجاح!")
        except subprocess.CalledProcessError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--user"] + missing,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print("✅ تم تثبيت جميع المكتبات بنجاح!")
            except subprocess.CalledProcessError:
                print(f"❌ فشل التثبيت التلقائي. شغّل يدوياً:")
                print(f"   pip install {' '.join(missing)}")
                sys.exit(1)

_install_missing()

# ══════════════════════════════════════════════════════════════════════════════
# Imports
# ══════════════════════════════════════════════════════════════════════════════
import os
import json
import base64
import logging
import ssl
import time
import gzip
import threading
import argparse
import webbrowser
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import bcrypt
import certifi

import uvicorn
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

# ══════════════════════════════════════════════════════════════════════════════
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
DEFAULT_MIN_QUALITY = 70
DEFAULT_MIN_RR = 1.5
DEFAULT_MIN_LIQUIDITY = 40
DEFAULT_MIN_CONFIRMATION = 3
DEFAULT_MIN_ADX = 20
DEFAULT_MIN_REL_VOL = 1.2
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

SECRET_KEY: str = os.getenv("EGX_SECRET_KEY", "egx-v2-default-secret-change-me")
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

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# =============================================================================
# القاعدة الأساسية لجميع النماذج
# Base class for all ORM models
# =============================================================================
Base = declarative_base()

# =============================================================================
# مسار قاعدة البيانات - قابل للتهيئة عبر متغير البيئة
# Database path - configurable via environment variable
# =============================================================================
DB_PATH = os.getenv(
    "EGX_DB_PATH",
    str(DATA_DIR / "egx_v2.db")
)

# =============================================================================
# محرك قاعدة البيانات والجلسات
# Database engine and session factory
# =============================================================================
_engine = None
_SessionFactory = None


def _get_engine():
    """
    الحصول على محرك قاعدة البيانات - إنشاء واحد فقط (Singleton)
    Get the database engine - create only one (Singleton)
    """
    global _engine
    if _engine is None:
        # التأكد من وجود المجلد الأب لقاعدة البيانات
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"تم إنشاء مجلد قاعدة البيانات: {db_dir}")

        # إنشاء المحرك مع إعدادات SQLite المناسبة
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False},  # السماح بالاستخدام من خيوط متعددة
            pool_pre_ping=True,  # التحقق من صحة الاتصال قبل الاستخدام
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
    # وقف الخسارة
    stop_loss = Column(Float, nullable=True)
    # الأهداف - مخزنة كنص JSON
    targets = Column(Text, nullable=True)
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
        return {
            "id": self.id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "shares": self.shares,
            "signal_log_id": self.signal_log_id,
            "q1_qty": self.q1_qty,
            "q2_qty": self.q2_qty,
            "q3_qty": self.q3_qty,
            "stop_loss": self.stop_loss,
            "targets": json.loads(targets_raw) if targets_raw else [],
            "status": self.status,
            "pnl": self.pnl,
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
    # --- نهاية الحقول الموسعة ---
    # تاريخ الإنشاء
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """تحويل النموذج إلى قاموس"""
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
        ],
        "trades": [
            "signal_log_id INTEGER",
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
                trade.pnl = (exit_price - trade.entry_price) * trade.shares
                trade.pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
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
    # تحويل التوقيت العالمي إلى توقيت القاهرة (UTC+2)
    now = datetime.utcnow() + timedelta(hours=2)

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
    # تحويل التوقيت العالمي إلى توقيت القاهرة (UTC+2)
    now = datetime.utcnow() + timedelta(hours=2)
    weekday = now.weekday()

    # التحقق من عطلة نهاية الأسبوع
    if weekday >= 4:
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

        try:
            with urlopen(req, timeout=self.REQUEST_TIMEOUT, context=self._ssl_context) as response:
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
        جلب بيانات مؤشر EGX30 من TradingView

        يقوم بإرسال طلب POST إلى واجهة الرموز للحصول على
        السعر الحالي ونسبة التغيير لمؤشر EGX30.

        المعطيات:
            symbol: رمز المؤشر (الافتراضي: "EGX30")

        المخرجات:
            tuple من (السعر, نسبة_التغيير) أو (None, None) عند الفشل
        """
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

            if not data_list:
                logger.warning("لم يتم العثور على بيانات للمؤشر %s", symbol)
                return None, None

            values = data_list[0].get("d", [None, None])
            price = values[0] if len(values) > 0 else None
            change = values[1] if len(values) > 1 else None

            logger.info(
                "تم جلب بيانات المؤشر %s: السعر=%.2f، التغيير=%.2f%%",
                symbol, price or 0, change or 0,
            )
            return price, change

        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("خطأ في تحليل بيانات المؤشر %s: %s", symbol, exc)
            return None, None
        except (ConnectionError, TimeoutError) as exc:
            logger.error("خطأ في الاتصال أثناء جلب المؤشر %s: %s", symbol, exc)
            return None, None
        except Exception as exc:
            logger.error("خطأ غير متوقع أثناء جلب المؤشر %s: %s", symbol, exc)
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
                name_en=get_value(12, symbol),
                eps=get_value(13),  # earnings_per_share_basic_ttm
                rsi=round(get_value(14), 1) if get_value(14) is not None else None,
                rating=rating,
                rec_raw=rec_raw,
                div_yield=get_value(16),
                sector_en=sector_en,
                sector=sector_ar,
                industry=get_value(18),
                tv_name=get_value(19, symbol),
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

        # ── أهداف جني الأرباح ──
        targets = [
            round(max(fib.get("R1", 0), pivots.get("R1", 0)), 3),
            round(max(fib.get("R2", 0), pivots.get("R2", 0)), 3),
            round(max(fib.get("R3", 0), pivots.get("R3", 0)), 3),
        ]
        # أهداف قريبة ATR (محسوبة من entry_ideal)
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
            near_targets = [round(entry_ideal - r * atr, 3) for r in [1.0, 1.5, 2.5]]
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
    المستوى 1: بعد الهدف القريب 1 → الوقف يتحرك لسعر الدخول (صفقة بلا خسارة)
    المستوى 2: بعد الهدف القريب 2 → الوقف يتحرك للهدف القريب 1
    المستوى 3: بعد الهدف القريب 3 → الوقف يتحرك للهدف القريب 2
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
        {
            "level": 1,
            "trigger": near_targets[0] if near_targets else None,
            "new_stop": round(entry_price * 1.001, 3),  # فوق الدخول بـ 0.1%
            "ar": f"بعد الهدف 1 → حرّك الوقف لـ {round(entry_price * 1.001, 2)} (صفر خسارة) ✅",
            "risk": "صفر مخاطرة",
        },
    ]
    if len(near_targets) >= 2:
        levels.append({
            "level": 2,
            "trigger": near_targets[1],
            "new_stop": round(near_targets[0], 3),
            "ar": f"بعد الهدف 2 → حرّك الوقف لـ {round(near_targets[0], 2)} (ربح مضمون) 💰",
            "risk": "ربح مضمون",
        })
    if len(near_targets) >= 3:
        levels.append({
            "level": 3,
            "trigger": near_targets[2],
            "new_stop": round(near_targets[1], 3),
            "ar": f"بعد الهدف 3 → حرّك الوقف لـ {round(near_targets[1], 2)} 💰💰",
            "risk": "ربح أكبر مضمون",
        })
    if far_targets:
        levels.append({
            "level": 4,
            "trigger": far_targets[0],
            "new_stop": round(near_targets[-1], 3) if near_targets else round(entry_price * 1.05, 3),
            "ar": "بعد الهدف البعيد 1 → حرّك الوقف للهدف القريب الأخير 🏆",
            "risk": "ربح كبير محمي",
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
    التوقيت: بتوقيت القاهرة (UTC+2)
    """
    now = datetime.utcnow() + timedelta(hours=2)
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
    high52   = d.get("high52w")  or price * 1.1
    low52    = d.get("low52w")   or price * 0.9
    high3m   = d.get("high3m")   or price * 1.05
    low3m    = d.get("low3m")    or price * 0.95
    day_high = d.get("day_high") or price
    day_low  = d.get("day_low")  or price
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
    price_prev = d.get("price_prev") or price
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
Q1_RATIO = 0.30
Q2_RATIO = 0.30
Q3_RATIO = 0.40


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

    # توزيع الكمية على الأهداف (30% / 30% / 40%)
    q1 = int(shares * Q1_RATIO)
    q2 = int(shares * Q2_RATIO)
    q3 = shares - q1 - q2

    # التوقيت الحالي
    # Cairo time = UTC + 2
    cairo_now = datetime.utcnow() + timedelta(hours=2)
    now_str  = cairo_now.strftime("%H:%M")
    date_str = cairo_now.strftime("%Y-%m-%d")

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
        # الأهداف القريبة
        "near_t1":     near_t[0] if len(near_t) > 0 else None,
        "near_t2":     near_t[1] if len(near_t) > 1 else None,
        "near_t3":     near_t[2] if len(near_t) > 2 else None,
        # الأهداف البعيدة
        "far_t1":      far_t[0]  if len(far_t) > 0  else None,
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
        "CLOSE_T1":   "🎯 جني أرباح — الهدف 1",
        "CLOSE_T2":   "🎯 جني أرباح — الهدف 2",
        "CLOSE_T3":   "🏆 جني أرباح — الهدف 3",
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
            f"  الجزء 1 ({q1} سهم) → اجني عند {near_t[0] if near_t else '—'} ج (+{near_p[0] if near_p else '—'}%)",
            f"  الجزء 2 ({q2} سهم) → اجني عند {near_t[1] if len(near_t) > 1 else '—'} ج (+{near_p[1] if len(near_p) > 1 else '—'}%)",
            f"  الجزء 3 ({q3} سهم) → اجني عند {near_t[2] if len(near_t) > 2 else '—'} ج (+{near_p[2] if len(near_p) > 2 else '—'}%)",
            f"{'─' * 36}",
            f"R:R الهدف 1: {rr1}x | جودة: {round(tq, 0)}/100",
            f"تأكيد: {conf.get('label', '')} ({conf.get('bull_count', 0)} مؤشر)",
            f"سيولة: {liq}",
            f"الاستثمار: {round(total_cost / cap * 100, 1) if cap else '—'}% من رأس المال",
            f"أقصى خسارة: {round(shares * risk_per_share, 0)} ج ({risk_pct}%)",
        ]
    elif action in ("CLOSE_T1", "CLOSE_T2", "CLOSE_T3"):
        # تحديد فهرس الهدف
        tgt_idx = {"CLOSE_T1": 0, "CLOSE_T2": 1, "CLOSE_T3": 2}[action]
        qty     = [q1, q2, q3][tgt_idx]
        tgt_p   = near_t[tgt_idx] if tgt_idx < len(near_t) else price
        pct     = near_p[tgt_idx] if tgt_idx < len(near_p) else 0
        lines += [
            f"{'─' * 36}",
            f"اجني: {qty} سهم بسعر {tgt_p} ج",
            f"الربح: +{pct}% من الدخول",
            f"بعد التنفيذ: حرّك الوقف → {entry} ج",
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

        # إعادة تعيين الخسارة اليومية إذا كان يوم جديد
        self._reset_daily_pnl_if_new_day()

        # تحميل الإعدادات والصفقات
        trades = load_trades()
        open_trades = {tr["symbol"]: tr for tr in trades if tr.get("status") == "active"}
        open_count  = len(open_trades)

        # قراءة عتبات الإعدادات
        cap         = settings.get("capital", DEFAULT_CAPITAL)
        max_open    = settings.get("max_open_trades", DEFAULT_MAX_OPEN)
        min_quality = settings.get("min_quality", DEFAULT_MIN_QUALITY)
        min_rr      = settings.get("min_rr", DEFAULT_MIN_RR)
        min_liq     = settings.get("min_liq", DEFAULT_MIN_LIQUIDITY)
        min_confirm = settings.get("min_confirm", DEFAULT_MIN_CONFIRMATION)
        min_adx     = settings.get("min_adx", DEFAULT_MIN_ADX)
        min_rel_vol = settings.get("min_rel_vol", DEFAULT_MIN_REL_VOL)
        max_risk_pct_stop = settings.get("max_risk_pct", DEFAULT_MAX_RISK_PCT_PER_TRADE)
        max_consec_loss   = settings.get("max_consecutive_losses", DEFAULT_MAX_CONSECUTIVE_LOSSES)
        self._max_consecutive_losses = max_consec_loss

        # التحقق من حد الخسارة اليومي
        daily_limit_egp = cap * self._daily_loss_limit / 100
        if self._daily_pnl < -daily_limit_egp:
            logger.warning(
                "⛔ تم بلوغ حد الخسارة اليومي: %.2f ج (الحد: %.2f ج) — توقف التداول",
                self._daily_pnl, -daily_limit_egp,
            )
            return

        changed = False

        # ══════════════════════════════════════════════════════════════
        # فحص كل سهم لاتخاذ القرارات
        # ══════════════════════════════════════════════════════════════
        for sym, stock_data in stocks.items():
            # تحويل StockData إلى قاموس للتوافق مع الدوال الحالية
            v = stock_data.to_dict() if hasattr(stock_data, "to_dict") else stock_data

            a = v.get("analysis", {})
            if not a:
                continue
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
            # فلاتر جديدة: ADX, حجم نسبي, اتجاه السعر, المخاطرة
            # ════════════════════════════════════════════════════════
            adx_val    = v.get("adx") or 0
            rel_vol    = (v.get("volume", 0) / v.get("avg_vol", 1)) if v.get("avg_vol", 0) > 0 else 0
            price_ma   = v.get("price", 0)
            sma50_val  = v.get("sma50")
            price_above_sma50 = (price_ma and sma50_val and price_ma > sma50_val) if (price_ma and sma50_val) else True
            entry_ideal_check = t.get("entry_ideal", price)
            stop_loss_check   = t.get("stop_loss", price * 0.95)
            risk_per_share_chk = abs(entry_ideal_check - stop_loss_check) if (entry_ideal_check and stop_loss_check) else 0
            risk_pct_check = (risk_per_share_chk / entry_ideal_check * 100) if entry_ideal_check > 0 else 0

            # ════════════════════════════════════════════════════════
            # قرار 1: هل نفتح صفقة جديدة؟
            # ════════════════════════════════════════════════════════
            # التحقق من الخسائر المتتالية
            consec_loss_ok = self._consecutive_losses < max_consec_loss

            # تسجيل سبب رفض السهم (عشان التشخيص)
            if sig_type in BUY_SIGNALS and sym not in open_trades:
                reason = None
                if not settings.get("auto_open"): reason = "auto_open = OFF"
                elif open_count >= max_open: reason = f"open_count ({open_count}) >= max ({max_open})"
                elif tq < min_quality: reason = f"trade_quality ({tq}) < min ({min_quality})"
                elif rr1_val < min_rr: reason = f"rr1 ({rr1_val}) < min ({min_rr})"
                elif liq < min_liq: reason = f"liq ({liq}) < min ({min_liq})"
                elif bull_c < min_confirm: reason = f"bull_count ({bull_c}) < min ({min_confirm})"
                elif scen not in ENTRY_SCENARIOS_ALLOWED: reason = f"scenario ({scen}) غير مسموح"
                elif adx_val < min_adx: reason = f"ADX ({adx_val:.1f}) < {min_adx}"
                elif rel_vol < min_rel_vol: reason = f"rel_vol ({rel_vol:.1f}) < {min_rel_vol}"
                elif not price_above_sma50: reason = f"price ({price_ma}) <= SMA50 ({sma50_val})"
                elif risk_pct_check > max_risk_pct_stop: reason = f"risk_pct ({risk_pct_check:.1f}%) > {max_risk_pct_stop}%"
                elif not consec_loss_ok: reason = f"consec_losses ({self._consecutive_losses}) >= max ({max_consec_loss})"
                elif was_sent(sym, "OPEN"): reason = "تم إرسال إشارة OPEN من قبل"
                if reason:
                    logger.info("  [رفض] %s ← %s", sym, reason)

            if (
                settings.get("auto_open")
                and sym not in open_trades
                and open_count < max_open
                and sig_type in BUY_SIGNALS
                and tq >= min_quality
                and rr1_val >= min_rr
                and liq >= min_liq
                and bull_c >= min_confirm
                and scen in ENTRY_SCENARIOS_ALLOWED
                and adx_val >= min_adx
                and rel_vol >= min_rel_vol
                and price_above_sma50
                and risk_pct_check <= max_risk_pct_stop
                and consec_loss_ok
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
                    self._open_trade(sym, t, a, v, settings, trades, open_trades, signal_log_id=sig_id)
                    open_count += 1
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
            if sym in open_trades and settings.get("auto_close"):
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
                        self._daily_pnl += pnl_egp
                        # تتبع الخسائر المتتالية
                        if pnl_egp < 0:
                            self._consecutive_losses += 1
                            logger.warning(
                                "⚠️ خسارة متتالية #%d/%d — %s (%.2f ج)",
                                self._consecutive_losses, max_consec_loss, sym, pnl_egp,
                            )
                        else:
                            self._consecutive_losses = 0
                        # تسجيل نتيجة الإشارة للباك تيست
                        sig_id = tr.get("signal_log_id")
                        if sig_id:
                            update_signal_result(
                                sig_id, "LOSS" if pnl_egp < 0 else "WIN",
                                pnl_egp, pnl_pct, price, "STOP",
                            )
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
                    ("near_t1", "CLOSE_T1", "q1_open"),
                    ("near_t2", "CLOSE_T2", "q2_open"),
                    ("near_t3", "CLOSE_T3", "q3_open"),
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
                            # تحديث الكمية المتبقية
                            tr[q_key] = 0
                            # ── وقف الخسارة المتحرك (Trailing Stop) ──
                            changed = self._apply_trailing_stop(
                                i, sym, v, a, t, settings, tr, ep
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
        })
        signal_log_id = log_result.get("db_id") if log_result else None

        # تسجيل في السجل
        logger.info(
            "  📡 إشارة جديدة: %s %s @ %s",
            card.get("action", ""), card.get("symbol", ""), card.get("price", ""),
        )

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
        """
        price    = v.get("price", 0)
        cap      = settings.get("capital", DEFAULT_CAPITAL)
        risk_pct = settings.get("risk_pct", DEFAULT_RISK_PCT)

        entry_p = t.get("entry_ideal", price)
        near_t  = t.get("near_targets", [])
        near_p  = t.get("near_pcts", [])
        far_t   = t.get("targets", [])
        tq      = t.get("trade_quality", 0) or 0

        rps    = abs(entry_p - t.get("stop_loss", entry_p * 0.95))
        shares = int((cap * risk_pct / 100) / rps) if rps > 0 else 0
        q1     = int(shares * Q1_RATIO)
        q2     = int(shares * Q2_RATIO)
        q3     = shares - q1 - q2

        new_trade: Dict[str, Any] = {
            "symbol":         sym,
            "entry_price":    entry_p,
            "shares":         shares,
            "q1_qty":         q1,
            "q2_qty":         q2,
            "q3_qty":         q3,
            "q1_open":        q1,
            "q2_open":        q2,
            "q3_open":        q3,
            "stop_loss":      t.get("stop_loss"),
            "near_t1":        near_t[0] if len(near_t) > 0 else None,
            "near_t2":        near_t[1] if len(near_t) > 1 else None,
            "near_t3":        near_t[2] if len(near_t) > 2 else None,
            "near_p1":        near_p[0] if len(near_p) > 0 else None,
            "near_p2":        near_p[1] if len(near_p) > 1 else None,
            "near_p3":        near_p[2] if len(near_p) > 2 else None,
            "target1":        far_t[0]  if len(far_t) > 0  else None,
            "trade_quality":  round(tq, 1),
            "signal_type":    a.get("signal_type", ""),
            "entry_scenario": t.get("entry_scenario", "WAIT"),
            "notes":          f"تلقائي — {a.get('signal', '')} — جودة {round(tq, 0)}",
            "status":         "active",
            "auto":           True,
            "signal_log_id":  signal_log_id,
            "entry_date":     datetime.utcnow().isoformat(),
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
        target_idx: int,
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
        - بعد الهدف 1: حرّك الوقف لسعر الدخول (صفقة بلا خسارة)
        - بعد الهدف 2: حرّك الوقف للهدف 1
        - بعد الهدف 3: حرّك الوقف للهدف 2 + غلق الصفقة إذا اكتمل الجني

        المعطيات:
            target_idx:  فهرس الهدف الذي تم بلوغه (0, 1, 2)
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

        if target_idx == 0:
            # بعد الهدف 1 → الوقف لسعر الدخول (صفقة بلا خسارة)
            self._consecutive_losses = 0  # نجحت صفقة → إعادة تعيين الخسائر المتتالية
            new_sl = round(entry_price * 1.001, 3)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (سعر الدخول)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

        elif target_idx == 1:
            # بعد الهدف 2 → الوقف للهدف 1
            new_sl = tr.get("near_t1", entry_price)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (الهدف 1)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

        elif target_idx == 2:
            # بعد الهدف 3 → الوقف للهدف 2
            new_sl = tr.get("near_t2", entry_price)
            trail_card = build_signal_card(
                sym, v, a, t, ACTION_TRAIL_STOP,
                f"{new_sl} ج (الهدف 2)",
                settings,
            )
            self._push_signal(trail_card)
            tr["stop_loss"] = new_sl
            changed = True

            # لو الأجزاء الثلاثة اتجنت → غلق الصفقة
            if tr.get("q1_open", 0) == 0 and tr.get("q2_open", 0) == 0:
                pnl_pct = round((price - entry_price) / entry_price * 100, 2) if entry_price else 0
                pnl_egp = round((price - entry_price) * tr.get("q3_qty", tr.get("q3", 0)), 2) if entry_price else 0
                self._daily_pnl += pnl_egp
                self._consecutive_losses = 0  # نجاح → إعادة تعيين الخسائر المتتالية
                # تسجيل نتيجة الإشارة للباك تيست
                sig_id = tr.get("signal_log_id")
                if sig_id:
                    update_signal_result(
                        sig_id, "WIN",
                        pnl_egp, pnl_pct, price, "TARGETS",
                    )
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

        elif pending_type in ("CLOSE_T1", "CLOSE_T2", "CLOSE_T3"):
            sym        = pending["sym"]
            tr         = pending["trade"]
            target_idx = pending["target_idx"]

            # تحديث الكمية المتبقية
            q_keys = ["q1_open", "q2_open", "q3_open"]
            if target_idx < len(q_keys):
                tr[q_keys[target_idx]] = 0

            # تطبيق وقف الخسارة المتحرك
            trades = load_trades()
            v = pending.get("card", {})
            self._apply_trailing_stop(
                target_idx, sym, v, {}, {},
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
# HTML Frontend (embedded) - الواجهة الأمامية
# ══════════════════════════════════════════════════════════════════════════════

def _get_html_frontend() -> str:
    """تحميل واجهة المستخدم من ملف خارجي (مع fallback)"""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    try:
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        logger.warning(f"فشل تحميل index.html: {e}")
    return _EMBEDDED_HTML

_EMBEDDED_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>محلل البورصة المصرية - EGX Analyzer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;600;700;900&family=Rajdhani:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg-primary:    #0a0e1a;
  --bg-secondary:  #0f1526;
  --bg-card:       #131929;
  --bg-card-hover: #1a2035;
  --border:        rgba(99,179,237,0.12);
  --border-bright: rgba(99,179,237,0.3);
  --accent-blue:   #63b3ed;
  --accent-cyan:   #4fd1c5;
  --accent-green:  #68d391;
  --accent-yellow: #f6e05e;
  --accent-orange: #f6ad55;
  --accent-red:    #fc8181;
  --accent-purple: #b794f4;
  --text-primary:  #e2e8f0;
  --text-secondary:#94a3b8;
  --text-muted:    #475569;
  --buy-strong:    #00e676;
  --buy:           #69f0ae;
  --accumulate:    #f6e05e;
  --wait:          #b0bec5;
  --avoid:         #ff8a65;
  --sell:          #ff5252;
  --sell-strong:   #ff1744;
  --glow-blue:     0 0 20px rgba(99,179,237,0.2);
  --glow-green:    0 0 20px rgba(104,211,145,0.25);
  --glow-red:      0 0 20px rgba(252,129,129,0.25);
  --radius:        12px;
  --radius-sm:     8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'Cairo', sans-serif;
  font-size: 14px;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-secondary); }
::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }

/* ── Layout ── */
#app { display: flex; flex-direction: column; min-height: 100vh; }

/* ── Header ── */
.header {
  background: linear-gradient(135deg, #0f1526 0%, #131929 100%);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 20px;
  height: 64px;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(10px);
}
.header-logo {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-logo .logo-icon {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.header-logo h1 {
  font-size: 17px; font-weight: 700;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.header-logo .subtitle {
  font-size: 11px; color: var(--text-muted);
  display: block;
}
.header-spacer { flex: 1; }
.header-status {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-secondary);
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent-green);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%,100% { opacity:1; transform:scale(1); }
  50% { opacity:0.5; transform:scale(0.8); }
}
.btn-refresh {
  background: rgba(99,179,237,0.1);
  border: 1px solid var(--border-bright);
  color: var(--accent-blue);
  padding: 7px 14px; border-radius: 8px;
  cursor: pointer; font-family: 'Cairo', sans-serif; font-size: 13px;
  transition: all 0.2s;
  display: flex; align-items: center; gap: 6px;
}
.btn-refresh:hover { background: rgba(99,179,237,0.2); transform: translateY(-1px); }
.btn-refresh.loading { opacity: 0.6; pointer-events: none; }

/* ── Nav Tabs ── */
.nav-tabs {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  display: flex;
  padding: 0 24px;
  gap: 4px;
  overflow-x: auto;
}
.nav-tab {
  padding: 12px 18px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.2s;
  white-space: nowrap;
  display: flex; align-items: center; gap: 7px;
}
.nav-tab:hover { color: var(--text-primary); }
.nav-tab.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}
.nav-badge {
  background: var(--accent-blue);
  color: #000;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
  min-width: 20px;
  text-align: center;
}

/* ── Main Content ── */
.main-content {
  flex: 1;
  padding: 20px 24px;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

/* ── Views ── */
.view { display: none; }
.view.active { display: block; }

/* ── KPI Row ── */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  transition: all 0.2s;
}
.kpi-card:hover {
  border-color: var(--border-bright);
  box-shadow: var(--glow-blue);
  transform: translateY(-2px);
}
.kpi-label { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
.kpi-value { font-size: 22px; font-weight: 700; font-family: 'Rajdhani', sans-serif; }
.kpi-sub   { font-size: 11px; color: var(--text-secondary); margin-top: 3px; }

/* ── Filters ── */
.filters-bar {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}
.filter-group { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
.filter-input, .filter-select {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 7px 12px;
  border-radius: var(--radius-sm);
  font-family: 'Cairo', sans-serif;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.filter-input:focus, .filter-select:focus { border-color: var(--accent-blue); }
.filter-input { min-width: 180px; }
.filter-select { min-width: 120px; cursor: pointer; }
.filter-spacer { flex: 1; }

/* ── Table ── */
.table-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.table-wrap table {
  width: 100%;
  border-collapse: collapse;
}
.table-wrap th {
  background: var(--bg-secondary);
  padding: 11px 14px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  transition: color 0.2s;
}
.table-wrap th:hover { color: var(--accent-blue); }
.table-wrap td {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(99,179,237,0.06);
  font-size: 13px;
  white-space: nowrap;
}
.table-wrap tr:last-child td { border-bottom: none; }
.table-wrap tr:hover td { background: var(--bg-card-hover); cursor: pointer; }

/* ── Signal Badges ── */
.sig-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 20px;
  font-size: 12px; font-weight: 600;
}

/* ── Score Bar ── */
.score-bar {
  display: flex; align-items: center; gap: 8px;
}
.score-track {
  flex: 1; height: 5px;
  background: rgba(255,255,255,0.08);
  border-radius: 3px; overflow: hidden;
  min-width: 60px;
}
.score-fill {
  height: 100%; border-radius: 3px;
  transition: width 0.4s ease;
}
.score-num {
  font-family: 'Rajdhani', sans-serif;
  font-size: 13px; font-weight: 700;
  min-width: 28px; text-align: left;
}

/* ── Colors ── */
.green  { color: var(--accent-green); }
.red    { color: var(--accent-red); }
.yellow { color: var(--accent-yellow); }
.cyan   { color: var(--accent-cyan); }
.blue   { color: var(--accent-blue); }
.muted  { color: var(--text-muted); }
.orange { color: var(--accent-orange); }

/* ── Stock Detail Modal ── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.75);
  backdrop-filter: blur(4px);
  z-index: 200;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}
@keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
.modal {
  background: var(--bg-card);
  border: 1px solid var(--border-bright);
  border-radius: 16px;
  width: 100%;
  max-width: 900px;
  max-height: 90vh;
  overflow-y: auto;
  animation: slideUp 0.25s ease;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
}
@keyframes slideUp { from { transform:translateY(20px); opacity:0; } to { transform:translateY(0); opacity:1; } }
.modal-header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: flex-start; gap: 16px;
}
.modal-sym {
  font-family: 'Rajdhani', sans-serif;
  font-size: 32px; font-weight: 700;
  color: var(--accent-blue);
  line-height: 1;
}
.modal-name { font-size: 13px; color: var(--text-secondary); margin-top: 4px; }
.modal-price { font-size: 26px; font-weight: 700; font-family: 'Rajdhani', sans-serif; }
.modal-change { font-size: 13px; margin-top: 4px; }
.modal-close {
  margin-right: auto;
  background: none; border: 1px solid var(--border);
  color: var(--text-secondary);
  width: 32px; height: 32px;
  border-radius: 8px; cursor: pointer;
  font-size: 16px; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
.modal-close:hover { border-color: var(--accent-red); color: var(--accent-red); }
.modal-body { padding: 20px 24px; }

/* Modal Grid */
.modal-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media(max-width:650px) { .modal-grid { grid-template-columns: 1fr; } }

.info-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
}
.info-section h3 {
  font-size: 13px; font-weight: 600;
  color: var(--accent-cyan);
  margin-bottom: 12px;
  display: flex; align-items: center; gap: 6px;
}
.info-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 5px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.info-row:last-child { border-bottom: none; }
.info-key  { font-size: 12px; color: var(--text-secondary); }
.info-val  { font-size: 13px; font-weight: 600; }

/* Trade Plan */
.trade-plan {
  background: rgba(104,211,145,0.05);
  border: 1px solid rgba(104,211,145,0.2);
  border-radius: var(--radius);
  padding: 16px;
  grid-column: 1 / -1;
}
.trade-plan h3 { color: var(--accent-green); margin-bottom: 14px; font-size: 14px; }
.trade-grid {
  display: grid; grid-template-columns: repeat(3,1fr); gap: 12px;
  margin-bottom: 12px;
}
.trade-box {
  background: var(--bg-card); border-radius: var(--radius-sm);
  padding: 10px 12px; text-align: center;
}
.trade-box-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.trade-box-val   { font-size: 18px; font-weight: 700; font-family: 'Rajdhani', sans-serif; }
.targets-row { display: flex; gap: 10px; flex-wrap: wrap; }
.target-chip {
  background: rgba(99,179,237,0.1);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
}
.target-chip .t-label { color: var(--text-muted); font-size: 11px; }
.target-chip .t-price { font-family: 'Rajdhani', sans-serif; font-size: 16px; font-weight: 700; }
.target-chip .t-rr    { color: var(--accent-cyan); font-size: 11px; }

/* Fib levels */
.fib-levels {
  display: flex; flex-direction: column; gap: 3px;
  grid-column: 1 / -1;
}
.fib-row {
  display: flex; align-items: center; gap: 8px;
}
.fib-label { font-size: 11px; color: var(--text-muted); width: 50px; text-align: right; }
.fib-bar-wrap { flex: 1; height: 20px; position: relative; background: rgba(255,255,255,0.03); border-radius: 4px; overflow: hidden; }
.fib-bar-fill { position: absolute; top:0; height:100%; border-radius:4px; }
.fib-val { font-size: 12px; font-family: 'Rajdhani',sans-serif; width: 60px; text-align: left; color: var(--text-primary); }
.fib-price-line {
  position: absolute; top:0; width:2px; height:100%;
  background: var(--accent-yellow); z-index: 2;
}

/* ── Top Opportunities ── */
.top-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.top-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}
.top-card::before {
  content:'';
  position:absolute; top:0; right:0;
  width:3px; height:100%;
}
.top-card.BUY_STRONG::before  { background: var(--buy-strong); }
.top-card.BUY::before          { background: var(--buy); }
.top-card.ACCUMULATE::before   { background: var(--accumulate); }
.top-card:hover {
  border-color: var(--border-bright);
  transform: translateY(-2px);
  box-shadow: var(--glow-blue);
}
.top-card-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 10px;
}
.top-card-sym {
  font-family: 'Rajdhani', sans-serif;
  font-size: 20px; font-weight: 700;
  color: var(--accent-blue);
}
.top-card-name { font-size: 11px; color: var(--text-muted); }
.top-card-price { text-align: left; }
.top-card-price .price-val { font-family:'Rajdhani',sans-serif; font-size:18px; font-weight:700; }
.top-card-metrics {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 8px; margin: 10px 0;
}
.metric-item { text-align: center; }
.metric-label { font-size: 10px; color: var(--text-muted); }
.metric-val { font-size: 13px; font-weight: 600; font-family:'Rajdhani',sans-serif; }
.top-card-footer {
  display: flex; justify-content: space-between; align-items: center;
  border-top: 1px solid var(--border);
  padding-top: 10px; margin-top: 6px;
  font-size: 11px; color: var(--text-muted);
}

/* ── Screener ── */
.screener-chips {
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px;
}
.screener-chip {
  padding: 6px 14px; border-radius: 20px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer; font-family: 'Cairo', sans-serif; font-size: 12px;
  transition: all 0.2s;
}
.screener-chip:hover { border-color: var(--accent-blue); color: var(--accent-blue); }
.screener-chip.active { background: var(--accent-blue); color: #000; border-color: var(--accent-blue); font-weight: 600; }

/* ── RSI Gauge ── */
.rsi-gauge-wrap {
  display: flex; align-items: center; gap: 8px;
}
.rsi-bar {
  width: 80px; height: 6px;
  background: linear-gradient(90deg, var(--accent-green) 0%, var(--accent-yellow) 50%, var(--accent-red) 100%);
  border-radius: 3px; position: relative;
}
.rsi-pointer {
  position: absolute; top: -3px;
  width: 12px; height: 12px;
  background: #fff;
  border-radius: 50%;
  transform: translateX(-50%);
  border: 2px solid var(--bg-card);
}

/* ── Loading ── */
.loading-overlay {
  position: fixed; inset: 0;
  background: var(--bg-primary);
  z-index: 500;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 16px;
}
.loading-spinner {
  width: 48px; height: 48px;
  border: 3px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform:rotate(360deg); } }
.loading-text { color: var(--text-secondary); font-size: 14px; }

/* ── Empty ── */
.empty-state {
  text-align: center; padding: 60px 20px;
  color: var(--text-muted);
}
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* ── Stat Summary ── */
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px; margin-bottom: 16px;
}
.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: flex; align-items: center; gap: 12px;
}
.stat-icon { font-size: 24px; }
.stat-info {}
.stat-num { font-size: 20px; font-weight: 700; font-family:'Rajdhani',sans-serif; }
.stat-desc { font-size: 11px; color: var(--text-muted); }

/* ── Sector breakdown ── */
.sector-bars { display: flex; flex-direction: column; gap: 8px; }
.sector-bar-row { display: flex; align-items: center; gap: 10px; }
.sector-name { font-size: 12px; width: 120px; text-align: right; color: var(--text-secondary); }
.sector-bar-track { flex:1; height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden; }
.sector-bar-fill  { height:100%; border-radius:4px; background: var(--accent-blue); }
.sector-count { font-size: 11px; color: var(--text-muted); width: 30px; text-align: left; }

/* ── Chart placeholder ── */
.mini-chart {
  height: 40px; display: flex; align-items: flex-end; gap: 2px;
}
.mini-bar {
  flex: 1; border-radius: 2px 2px 0 0;
  min-height: 3px;
  opacity: 0.7;
}

/* ── Divergence Badge ── */
.div-badge {
  display:inline-flex; align-items:center; gap:5px;
  padding:4px 10px; border-radius:8px; font-size:12px; font-weight:600;
}
.div-bull { background:rgba(104,211,145,0.12); color:#68d391; border:1px solid rgba(104,211,145,0.3); }
.div-bear { background:rgba(252,129,129,0.12); color:#fc8181; border:1px solid rgba(252,129,129,0.3); }

/* ── Confirmation Meter ── */
.conf-meter { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.conf-dot   { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.conf-dots  { display:flex; gap:4px; }

/* ── Trailing Stop Timeline ── */
.trail-timeline { display:flex; flex-direction:column; gap:6px; }
.trail-step {
  display:flex; align-items:center; gap:10px;
  padding:7px 10px; border-radius:8px;
  background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06);
  font-size:12px;
}
.trail-step.active { background:rgba(0,230,118,0.08); border-color:rgba(0,230,118,0.25); }
.trail-num { font-family:Rajdhani,sans-serif; font-size:18px; font-weight:700;
             min-width:22px; text-align:center; }

/* ── Resistance Warning ── */
.res-warning {
  background:rgba(246,173,85,0.1); border:1px solid rgba(246,173,85,0.3);
  border-radius:8px; padding:8px 12px; font-size:12px; color:var(--accent-orange);
  display:flex; align-items:center; gap:8px;
}

/* ── Breadth Bar ── */
.breadth-bar {
  height:12px; border-radius:6px; overflow:hidden;
  display:flex; gap:1px;
}
.breadth-adv { background:var(--accent-green); transition:width 0.4s; }
.breadth-dec { background:var(--accent-red);   transition:width 0.4s; }
.breadth-unc { background:var(--text-muted);   transition:width 0.4s; }

/* ── Position Size Calculator ── */
.pos-calc {
  background:rgba(99,179,237,0.06); border:1px solid rgba(99,179,237,0.2);
  border-radius:var(--radius); padding:14px 16px;
}
.pos-calc h3 { font-size:13px; color:var(--accent-blue); margin-bottom:12px; }
.pos-result  { font-family:Rajdhani,sans-serif; font-size:22px; font-weight:700;
               color:var(--accent-cyan); }

/* ── Autopilot Signal Card ── */
.signal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: all 0.2s;
  position: relative;
}
.signal-card:hover { border-color: var(--border-bright); }
.signal-card.OPEN        { border-right: 4px solid var(--accent-green); }
.signal-card.CLOSE_T1,
.signal-card.CLOSE_T2,
.signal-card.CLOSE_T3    { border-right: 4px solid var(--accent-yellow); }
.signal-card.CLOSE_STOP  { border-right: 4px solid var(--accent-red); }
.signal-card.TRAIL_STOP  { border-right: 4px solid var(--accent-blue); }

.signal-header {
  display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
}
.signal-sym   { font-family:'Rajdhani',sans-serif; font-size:22px; font-weight:700; color:var(--accent-blue); }
.signal-action{ font-size:13px; font-weight:700; }
.signal-time  { font-size:11px; color:var(--text-muted); margin-right:auto; }

.signal-body  { font-size:12px; line-height:1.8; }
.signal-text  {
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px; padding: 10px 12px;
  font-family: 'Courier New', monospace;
  font-size: 11px; line-height: 1.7;
  color: var(--text-secondary); margin: 8px 0;
  white-space: pre-wrap; direction: rtl;
}
.copy-btn {
  background: rgba(99,179,237,0.1);
  border: 1px solid rgba(99,179,237,0.3);
  color: var(--accent-blue);
  padding: 6px 14px; border-radius: 8px;
  cursor: pointer; font-family:Cairo,sans-serif; font-size:12px;
  transition: all 0.15s; display:inline-flex; align-items:center; gap:6px;
}
.copy-btn:hover { background: rgba(99,179,237,0.2); }
.copy-btn.copied { background: rgba(104,211,145,0.15); color:var(--accent-green); border-color:rgba(104,211,145,0.3); }

/* settings inputs */
.setting-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.setting-row:last-child { border-bottom: none; }
.setting-label { font-size:12px; color:var(--text-secondary); }
.setting-input {
  background: var(--bg-primary); border: 1px solid var(--border);
  color: var(--text-primary); padding: 5px 10px; border-radius:6px;
  font-family:Cairo,sans-serif; font-size:12px; outline:none;
  width: 100px; text-align: center;
}
.setting-toggle {
  width: 40px; height: 22px; border-radius: 11px;
  position: relative; cursor: pointer; transition: background 0.2s;
  border: none; outline: none;
}
.setting-toggle.on  { background: var(--accent-green); }
.setting-toggle.off { background: rgba(255,255,255,0.15); }
.toggle-dot {
  position:absolute; top:3px; width:16px; height:16px;
  border-radius:50%; background:#fff; transition: left 0.2s;
}
.setting-toggle.on  .toggle-dot { left: 20px; }
.setting-toggle.off .toggle-dot { left: 3px; }

/* ── Print / PDF Export ── */
@media print {
  .header, .nav-tabs, .filters-bar, .btn-refresh, #alertBtn,
  .pagination, .close-btn, .del-btn, #addTradeModal { display: none !important; }
  body { background: #fff !important; color: #000 !important; }
  .kpi-card, .info-section, .trade-plan, .top-card {
    border: 1px solid #ddd !important; background: #fff !important;
  }
  .kpi-value, .modal-sym, .modal-price { color: #000 !important; }
  .green { color: #16a34a !important; }
  .red   { color: #dc2626 !important; }
  .main-content { padding: 0 !important; }
  @page { margin: 1cm; }
}

/* Sortable indicator */
th.sort-asc::after  { content: " ↑"; color: var(--accent-blue); }
th.sort-desc::after { content: " ↓"; color: var(--accent-blue); }

/* ── Heat Map ── */
.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px; padding: 4px 0;
}
.heatmap-cell {
  border-radius: 10px; padding: 10px 12px;
  cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;
  border: 1px solid rgba(255,255,255,0.06);
  position: relative; overflow: hidden;
}
.heatmap-cell:hover { transform: scale(1.03); box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
.hm-sector { font-size: 11px; color: rgba(255,255,255,0.7); margin-bottom: 4px; }
.hm-chg    { font-family:'Rajdhani',sans-serif; font-size: 20px; font-weight: 700; }
.hm-count  { font-size: 10px; color: rgba(255,255,255,0.5); margin-top: 2px; }

/* ── Market movers ── */
.mover-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
  cursor: pointer; transition: background 0.15s; border-radius: 6px;
}
.mover-row:hover { background: var(--bg-card-hover); padding: 8px 6px; }
.mover-row:last-child { border-bottom: none; }
.mover-sym { font-family:'Rajdhani',sans-serif; font-size:16px; font-weight:700;
             color:var(--accent-blue); min-width:60px; }
.mover-chg { font-family:'Rajdhani',sans-serif; font-size:15px; font-weight:700;
             min-width:55px; text-align:left; }
.mover-vs  { font-size:10px; color:var(--text-muted); }

/* ── Market Status Banner ── */
.market-banner {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; border-radius: 10px;
  margin-bottom: 16px;
  border: 1px solid;
}
.market-banner.open   { background:rgba(0,230,118,0.08); border-color:rgba(0,230,118,0.25); }
.market-banner.closed { background:rgba(148,163,184,0.06); border-color:rgba(148,163,184,0.15); }

/* ── Trades ── */
.trade-row-open   { border-right: 3px solid var(--accent-green); }
.trade-row-closed { border-right: 3px solid var(--text-muted); opacity: 0.75; }
.pnl-positive { color: var(--accent-green); font-family:'Rajdhani',sans-serif; font-weight:700; }
.pnl-negative { color: var(--accent-red);   font-family:'Rajdhani',sans-serif; font-weight:700; }
.close-btn {
  background: rgba(252,129,129,0.1); border: 1px solid rgba(252,129,129,0.3);
  color: var(--accent-red); padding: 4px 10px; border-radius: 6px;
  cursor: pointer; font-family:Cairo,sans-serif; font-size:11px;
  transition: all 0.15s;
}
.close-btn:hover { background: rgba(252,129,129,0.25); }
.del-btn {
  background: none; border: 1px solid var(--border);
  color: var(--text-muted); padding: 4px 8px; border-radius: 6px;
  cursor: pointer; font-size: 12px; transition: all 0.15s;
}
.del-btn:hover { border-color: var(--accent-red); color: var(--accent-red); }

/* close trade mini form */
.close-form {
  background: var(--bg-secondary); border: 1px solid var(--border-bright);
  border-radius: 10px; padding: 12px; margin-top: 8px;
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}
.close-form input { width: 130px; }

/* ADX badge */
.adx-badge {
  font-size: 10px; padding: 2px 7px; border-radius: 10px;
  font-weight: 600; display: inline-block;
}

/* Tooltip */
[data-tip] { position: relative; cursor: help; }
[data-tip]:hover::after {
  content: attr(data-tip);
  position: absolute; bottom: 120%; left: 50%; transform: translateX(-50%);
  background: #1a2035; border: 1px solid var(--border);
  color: var(--text-primary); font-size: 11px;
  padding: 4px 8px; border-radius: 6px;
  white-space: nowrap; z-index: 99;
  pointer-events: none;
}

/* pagination */
.pagination {
  display: flex; justify-content: center; align-items: center; gap: 6px;
  padding: 14px;
  border-top: 1px solid var(--border);
}
.page-btn {
  padding: 5px 10px; border-radius: 6px;
  border: 1px solid var(--border); background: transparent;
  color: var(--text-secondary); cursor: pointer; font-family:'Cairo',sans-serif; font-size:12px;
  transition: all 0.15s;
}
.page-btn:hover { border-color: var(--accent-blue); color: var(--accent-blue); }
.page-btn.active { background: var(--accent-blue); color:#000; border-color:var(--accent-blue); font-weight:600; }

/* ── Ready Badge ── */
.ready-badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 20px;
  font-size: 11px; font-weight: 700;
}
.ready-badge.ready   { background: rgba(0,230,118,0.15); color:#00e676; border:1px solid rgba(0,230,118,0.3); }
.ready-badge.near    { background: rgba(246,224,94,0.15); color:#f6e05e; border:1px solid rgba(246,224,94,0.3); }
.ready-badge.waiting { background: rgba(148,163,184,0.1); color:#94a3b8; border:1px solid rgba(148,163,184,0.2); }

/* ── Proximity Bar ── */
.proximity-wrap { display:flex; align-items:center; gap:6px; }
.proximity-track { flex:1; height:4px; border-radius:2px; background:rgba(255,255,255,0.08); overflow:hidden; min-width:50px; }
.proximity-fill  { height:100%; border-radius:2px; transition:width 0.4s; }
.proximity-num   { font-size:11px; font-family:'Rajdhani',sans-serif; min-width:30px; }

/* ── Quality Ring ── */
.quality-ring {
  width:52px; height:52px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-family:'Rajdhani',sans-serif; font-size:15px; font-weight:700;
  border:3px solid; flex-shrink:0;
}

/* ── Liquidity Bar ── */
.liq-bar-wrap { display:flex; align-items:center; gap:6px; }
.liq-track { flex:1; height:6px; border-radius:3px; background:rgba(255,255,255,0.08); overflow:hidden; }
.liq-fill  { height:100%; border-radius:3px; }

/* ── Entry Zone Diagram ── */
.entry-zone-diagram { background:var(--bg-secondary); border:1px solid var(--border); border-radius:var(--radius); padding:14px 16px; grid-column:1/-1; }
.entry-zone-diagram h3 { font-size:13px; font-weight:600; color:var(--accent-cyan); margin-bottom:14px; }
.entry-zone-track { position:relative; height:36px; background:rgba(255,255,255,0.04); border-radius:8px; overflow:visible; margin:22px 12px 24px; }
.ez-fill  { position:absolute; top:0; height:100%; background:rgba(99,179,237,0.15); border:1px solid rgba(99,179,237,0.3); border-radius:6px; }
.ez-marker{ position:absolute; top:-18px; transform:translateX(-50%); font-size:10px; white-space:nowrap; font-family:'Rajdhani',sans-serif; font-weight:700; }
.ez-line  { position:absolute; top:-6px; bottom:-6px; width:2px; border-radius:1px; }
.ez-label { position:absolute; bottom:-18px; transform:translateX(-50%); font-size:9px; white-space:nowrap; color:var(--text-muted); }

/* ── Top Card extras ── */
.top-card-quality { display:flex; align-items:center; gap:8px; padding:8px 0; border-top:1px solid var(--border); margin-top:8px; }
.top-card-entry-zone { font-size:11px; padding:8px 10px; background:rgba(99,179,237,0.05); border:1px solid rgba(99,179,237,0.15); border-radius:6px; margin-top:6px; }
.tez-row { display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }
.tez-label { color:var(--text-muted); font-size:10px; }
.tez-val { font-family:'Rajdhani',sans-serif; font-size:13px; font-weight:700; }

/* ══════════════════════════════════════════════
   ALERT SYSTEM
══════════════════════════════════════════════ */

/* ── Toast Container ── */
#toastContainer {
  position: fixed;
  top: 76px; left: 20px;
  z-index: 999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
  pointer-events: none;
}

/* ── Individual Toast ── */
.alert-toast {
  background: var(--bg-card);
  border-radius: 12px;
  padding: 12px 14px;
  border-right: 4px solid;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  animation: toastIn 0.3s cubic-bezier(.34,1.56,.64,1);
  pointer-events: all;
  cursor: pointer;
  transition: opacity 0.3s, transform 0.3s;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.alert-toast.fadeout {
  opacity: 0; transform: translateX(-20px);
}
@keyframes toastIn {
  from { opacity:0; transform: translateX(-30px) scale(0.9); }
  to   { opacity:1; transform: translateX(0)   scale(1);   }
}
.toast-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 6px;
}
.toast-sym {
  font-family: 'Rajdhani', sans-serif;
  font-size: 18px; font-weight: 700;
}
.toast-type {
  font-size: 12px; font-weight: 700;
  margin-right: auto;
}
.toast-close {
  background: none; border: none; color: var(--text-muted);
  cursor: pointer; font-size: 14px; padding: 0 2px;
  line-height: 1;
}
.toast-body { font-size: 12px; color: var(--text-secondary); }
.toast-price {
  font-family: 'Rajdhani', sans-serif;
  font-size: 20px; font-weight: 700;
  margin-top: 4px;
}
.toast-bar {
  height: 3px; border-radius: 2px;
  margin-top: 8px;
  animation: toastTimer linear forwards;
}
@keyframes toastTimer {
  from { width: 100%; }
  to   { width: 0%; }
}

/* ── Alert Bell Button ── */
#alertBtn {
  position: relative;
  background: rgba(246,224,94,0.08);
  border: 1px solid rgba(246,224,94,0.25);
  color: var(--accent-yellow);
  padding: 7px 14px; border-radius: 8px;
  cursor: pointer; font-family: 'Cairo',sans-serif; font-size: 13px;
  transition: all 0.2s;
  display: flex; align-items: center; gap: 6px;
}
#alertBtn:hover { background: rgba(246,224,94,0.15); }
#alertBtn.active { background: rgba(246,224,94,0.2); border-color: var(--accent-yellow); }
.alert-dot {
  position: absolute; top: -4px; right: -4px;
  width: 10px; height: 10px;
  background: var(--accent-red);
  border-radius: 50%; border: 2px solid var(--bg-primary);
  animation: pulse 1s infinite;
  display: none;
}
#alertBtn.has-alerts .alert-dot { display: block; }

/* ── Alert Panel ── */
#alertPanel {
  position: fixed;
  top: 72px; left: 20px;
  width: 400px;
  background: var(--bg-card);
  border: 1px solid var(--border-bright);
  border-radius: 14px;
  box-shadow: 0 16px 48px rgba(0,0,0,0.6);
  z-index: 300;
  display: none;
  overflow: hidden;
  animation: slideDown 0.2s ease;
}
@keyframes slideDown { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
.alert-panel-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px;
}
.alert-panel-header h3 { font-size: 14px; font-weight: 700; flex:1; }
.alert-panel-body { max-height: 480px; overflow-y: auto; }
.alert-item {
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  display: flex; align-items: center; gap: 10px;
  cursor: pointer; transition: background 0.15s;
}
.alert-item:hover { background: var(--bg-card-hover); }
.alert-item-sym {
  font-family: 'Rajdhani',sans-serif; font-size: 16px; font-weight: 700;
  color: var(--accent-blue); min-width: 60px;
}
.alert-item-info { flex:1; }
.alert-item-label { font-size: 12px; font-weight: 600; }
.alert-item-price { font-size: 11px; color: var(--text-muted); }
.alert-item-dismiss {
  background: none; border: 1px solid var(--border);
  color: var(--text-muted); border-radius: 6px;
  padding: 3px 8px; font-size: 11px; cursor: pointer;
  transition: all 0.15s; font-family:'Cairo',sans-serif;
}
.alert-item-dismiss:hover { border-color: var(--accent-red); color: var(--accent-red); }

/* ── Targets Display (near + far) ── */
.targets-section { margin-top: 10px; }
.targets-section-title {
  font-size: 11px; color: var(--text-muted);
  margin-bottom: 6px; font-weight: 600;
  display: flex; align-items: center; gap: 6px;
}
.targets-section-title::after {
  content:''; flex:1; height:1px; background:var(--border);
}
.targets-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.target-chip-near {
  background: rgba(104,211,145,0.08);
  border: 1px solid rgba(104,211,145,0.25);
  border-radius: 8px; padding: 5px 10px; text-align: center;
}
.target-chip-far {
  background: rgba(246,224,94,0.06);
  border: 1px solid rgba(246,224,94,0.2);
  border-radius: 8px; padding: 5px 10px; text-align: center;
}
.tc-label { font-size: 10px; color: var(--text-muted); }
.tc-price { font-family:'Rajdhani',sans-serif; font-size:15px; font-weight:700; }
.tc-pct   { font-size: 10px; font-weight: 600; margin-top: 1px; }
</style>
</head>
<body>
<div id="loadingOverlay" class="loading-overlay">
  <div class="loading-spinner"></div>
  <div class="loading-text">جاري تحميل بيانات البورصة المصرية...</div>
</div>

<div id="app" style="display:none">
  <!-- Header -->
  <!-- Risk Disclaimer Banner -->
  <div id="riskBanner" style="background:rgba(252,129,129,0.08);border-bottom:1px solid rgba(252,129,129,0.2);
       padding:6px 20px;text-align:center;font-size:11px;color:var(--accent-red);
       display:flex;align-items:center;justify-content:center;gap:8px">
    <span>⚠️</span>
    <span>تنويه مخاطر: هذا التطبيق للأغراض التعليمية فقط — لا يعتبر استشارة مالية — قرارات التداول تحمل مخاطر وقد تؤدي لخسارة رأس المال</span>
    <button onclick="this.parentElement.style.display='none'" style="background:none;border:none;color:var(--accent-red);cursor:pointer;font-size:14px;margin-right:10px">✕</button>
  </div>

  <header class="header">
    <div class="header-logo">
      <div class="logo-icon">📊</div>
      <div>
        <h1>EGX Analyzer <span style="font-size:10px;background:rgba(104,211,145,0.15);color:var(--accent-green);padding:2px 8px;border-radius:10px;border:1px solid rgba(104,211,145,0.3);vertical-align:middle">v2</span></h1>
        <span class="subtitle">محلل البورصة المصرية الإحصائي</span>
      </div>
    </div>
    <div class="header-spacer"></div>
    <!-- Security Badge -->
    <div id="securityBadge" style="display:flex;align-items:center;gap:6px;padding:4px 12px;border-radius:8px;
         background:rgba(104,211,145,0.08);border:1px solid rgba(104,211,145,0.2);cursor:pointer"
         onclick="showSecurityInfo()" title="معلومات الأمان">
      <span style="font-size:14px">🔒</span>
      <span style="font-size:11px;color:var(--accent-green)">مشفّر</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <input type="text" id="searchBox" placeholder="🔍 ابحث عن سهم... (Ctrl+F)"
        style="background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);
               padding:6px 12px;border-radius:8px;font-family:Cairo,sans-serif;font-size:13px;
               width:170px;outline:none;transition:all .2s"
        onfocus="this.style.borderColor='var(--accent-blue)';this.style.width='220px'"
        onblur="this.style.borderColor='var(--border)';this.style.width='170px'"
        oninput="quickSearch(this.value)">
    </div>
    <div class="header-status">
      <div class="status-dot" id="statusDot"></div>
      <span id="statusText">جاري التحميل...</span>
      <span id="nextRefreshCountdown" style="font-size:11px;color:var(--accent-cyan);margin-right:6px"></span>
    </div>
    <button class="btn-refresh" id="btnRefresh" onclick="doRefresh()">
      <span>🔄</span> تحديث
    </button>
    <button onclick="exportPDF()"
      style="background:rgba(179,122,237,0.08);border:1px solid rgba(179,122,237,0.25);
             color:var(--accent-purple);padding:7px 14px;border-radius:8px;
             cursor:pointer;font-family:Cairo,sans-serif;font-size:13px;
             display:flex;align-items:center;gap:6px">
      <span>📄</span> تصدير PDF
    </button>
    <!-- Password Setup Button -->
    <button onclick="showPasswordModal()"
      style="background:rgba(246,224,94,0.08);border:1px solid rgba(246,224,94,0.2);
             color:var(--accent-yellow);padding:7px 12px;border-radius:8px;
             cursor:pointer;font-family:Cairo,sans-serif;font-size:13px;
             display:flex;align-items:center;gap:4px" id="btnPassword" title="إعداد كلمة المرور">
      <span>🔑</span>
    </button>
    <button id="alertBtn" onclick="toggleAlertPanel()">
      <span>🔔</span> التنبيهات
      <div class="alert-dot"></div>
    </button>
  </header>

  <!-- Alert Panel -->
  <div id="alertPanel">
    <div class="alert-panel-header">
      <h3>🔔 التنبيهات النشطة</h3>
      <span id="alertPanelCount" style="font-size:12px;color:var(--text-muted)"></span>
      <button onclick="clearAllAlerts()" style="background:none;border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 10px;font-size:11px;cursor:pointer;font-family:Cairo,sans-serif">مسح الكل</button>
      <button onclick="toggleAlertPanel()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;margin-right:4px">✕</button>
    </div>
    <div class="alert-panel-body" id="alertPanelBody">
      <div style="padding:30px;text-align:center;color:var(--text-muted)">
        <div style="font-size:32px;margin-bottom:8px">🔔</div>
        <div>لا توجد تنبيهات نشطة</div>
        <div style="font-size:11px;margin-top:6px">التنبيهات تظهر تلقائياً عند إضافة أسهم للمتابعة</div>
      </div>
    </div>
  </div>

  <!-- Toast Container -->
  <div id="toastContainer"></div>

  <!-- Nav Tabs -->
  <nav class="nav-tabs">
    <div class="nav-tab active" onclick="switchTab('overview')">
      <span>🏠</span> نظرة عامة
    </div>
    <div class="nav-tab" onclick="switchTab('opportunities')">
      <span>🎯</span> أفضل الفرص
      <span class="nav-badge" id="badgeOpps">0</span>
    </div>
    <div class="nav-tab" onclick="switchTab('screener')">
      <span>🔍</span> الفاحص الإحصائي
    </div>
    <div class="nav-tab" onclick="switchTab('signals')">
      <span>📡</span> الإشارات
    </div>
    <div class="nav-tab" onclick="switchTab('watchlist')">
      <span>⭐</span> قائمة المتابعة
      <span class="nav-badge" id="badgeWatch">0</span>
    </div>
    <div class="nav-tab" onclick="switchTab('market')">
      <span>🌡️</span> السوق
    </div>
    <div class="nav-tab" onclick="switchTab('trades')">
      <span>📋</span> صفقاتي
      <span class="nav-badge" id="badgeTrades" style="background:var(--accent-green)">0</span>
    </div>
    <div class="nav-tab" onclick="switchTab('autopilot')">
      <span>🤖</span> الطيار الآلي
      <span class="nav-badge" id="badgeAuto" style="background:var(--accent-purple)">0</span>
    </div>
    <div class="nav-tab" onclick="switchTab('backtest')">
      <span>📊</span> باك تيست
    </div>
  </nav>

  <!-- Main Content -->
  <div class="main-content">

    <!-- ── Overview ── -->
    <div id="view-overview" class="view active">
      <div class="kpi-row" id="kpiRow"></div>
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px">
        <div>
          <div class="filters-bar">
            <div class="filter-group">
              <span class="filter-label">بحث:</span>
              <input class="filter-input" id="overSearch" placeholder="اسم السهم أو الرمز..." oninput="renderOverview()">
            </div>
            <div class="filter-group">
              <span class="filter-label">القطاع:</span>
              <select class="filter-select" id="overSector" onchange="renderOverview()">
                <option value="">كل القطاعات</option>
              </select>
            </div>
            <div class="filter-group">
              <span class="filter-label">الإشارة:</span>
              <select class="filter-select" id="overSignal" onchange="renderOverview()">
                <option value="">كل الإشارات</option>
                <option value="BUY_STRONG">شراء قوي</option>
                <option value="BUY">شراء</option>
                <option value="ACCUMULATE">تجميع</option>
                <option value="WAIT">انتظار</option>
                <option value="SELL">بيع</option>
                <option value="SELL_STRONG">بيع قوي</option>
              </select>
            </div>
            <div class="filter-spacer"></div>
            <span class="muted" id="overCount" style="font-size:12px"></span>
          </div>
          <div class="table-wrap">
            <table id="overTable">
              <thead>
                <tr>
                  <th onclick="sortTable('sym')">الرمز</th>
                  <th onclick="sortTable('price')">السعر</th>
                  <th onclick="sortTable('change')">التغيير%</th>
                  <th onclick="sortTable('signal')">الإشارة</th>
                  <th onclick="sortTable('score')">الزخم</th>
                  <th onclick="sortTable('rsi')">RSI</th>
                  <th onclick="sortTable('volume')">الحجم</th>
                  <th onclick="sortTable('adx')">ADX</th>
                  <th onclick="sortTable('vs_egx30')">vs EGX30</th>
                  <th onclick="sortTable('sector')">القطاع</th>
                  <th>⭐</th>
                </tr>
              </thead>
              <tbody id="overBody"></tbody>
            </table>
            <div class="pagination" id="overPager"></div>
          </div>
        </div>
        <div>
          <!-- Sector breakdown -->
          <div class="info-section" style="margin-bottom:14px">
            <h3>📊 توزيع القطاعات</h3>
            <div class="sector-bars" id="sectorBars"></div>
          </div>
          <!-- Signal distribution -->
          <div class="info-section">
            <h3>📡 توزيع الإشارات</h3>
            <div id="signalDist"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Opportunities ── -->
    <div id="view-opportunities" class="view">
      <div class="stat-row" id="oppStats"></div>
      <!-- فلترة برأس المال -->
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;
                  background:var(--bg-card);border:1px solid var(--border);
                  border-radius:var(--radius);padding:12px 16px;flex-wrap:wrap">
        <span style="font-size:13px;font-weight:600">🎯 فلترة الفرص</span>
        <div class="filter-group">
          <span class="filter-label">رأس المال المتاح:</span>
          <input id="capitalInput" class="filter-input" type="number" placeholder="مثال: 50000"
            style="width:140px" oninput="renderOpportunities();updatePosSizeHint()">
          <span style="font-size:12px;color:var(--text-muted)">ج.م</span>
        </div>
        <div class="filter-group">
          <span class="filter-label">% مخاطرة/صفقة:</span>
          <select id="riskPctSelect" class="filter-select" style="width:90px" onchange="renderOpportunities()">
            <option value="1">1%</option>
            <option value="2" selected>2%</option>
            <option value="3">3%</option>
            <option value="5">5%</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">الحد الأدنى للجودة:</span>
          <select id="minQualityFilter" class="filter-select" onchange="renderOpportunities()">
            <option value="0">كل الفرص</option>
            <option value="60">جيدة ≥ 60</option>
            <option value="80" selected>ممتازة ≥ 80</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">الإشارة:</span>
          <select id="oppSignalFilter" class="filter-select" onchange="renderOpportunities()">
            <option value="">الكل</option>
            <option value="BUY_STRONG">شراء قوي فقط</option>
            <option value="BUY">شراء فقط</option>
            <option value="ACCUMULATE">تجميع فقط</option>
          </select>
        </div>
        <span id="oppFilterCount" style="font-size:12px;color:var(--text-muted);margin-right:auto"></span>
      </div>
      <div class="top-grid" id="topGrid"></div>
    </div>

    <!-- ── Screener ── -->
    <div id="view-screener" class="view">
      <div class="screener-chips" id="screenerChips">
        <button class="screener-chip active" onclick="applyScreener('ALL',this)">🌐 الكل</button>
        <button class="screener-chip" onclick="applyScreener('RSI_OVERSOLD',this)">📉 RSI تشبع بيع &lt;30</button>
        <button class="screener-chip" onclick="applyScreener('RSI_OVERBOUGHT',this)">📈 RSI تشبع شراء &gt;70</button>
        <button class="screener-chip" onclick="applyScreener('HIGH_VOL',this)">⚡ حجم مرتفع</button>
        <button class="screener-chip" onclick="applyScreener('NEAR_52H',this)">🏔 قرب أعلى 52 أسبوع</button>
        <button class="screener-chip" onclick="applyScreener('NEAR_52L',this)">🏔 قرب أدنى 52 أسبوع</button>
        <button class="screener-chip" onclick="applyScreener('ABOVE_SMA200',this)">📊 فوق SMA200</button>
        <button class="screener-chip" onclick="applyScreener('GOLDEN_CROSS',this)">✨ تقاطع ذهبي</button>
        <button class="screener-chip" onclick="applyScreener('BB_SQUEEZE',this)">🎯 في نطاق بولينجر</button>
      </div>
      <div class="table-wrap">
        <table id="screenerTable">
          <thead>
            <tr>
              <th>الرمز</th>
              <th>السعر</th>
              <th>التغيير%</th>
              <th>RSI</th>
              <th>MACD</th>
              <th>ADX</th>
              <th>بولينجر%</th>
              <th>SMA20</th>
              <th>SMA200</th>
              <th>الحجم النسبي</th>
              <th>أداء شهري</th>
              <th>الإشارة</th>
            </tr>
          </thead>
          <tbody id="screenerBody"></tbody>
        </table>
        <div class="pagination" id="screenerPager"></div>
      </div>
    </div>

    <!-- ── Signals ── -->
    <div id="view-signals" class="view">
      <div class="filters-bar">
        <div class="filter-group">
          <span class="filter-label">نوع الإشارة:</span>
          <select class="filter-select" id="sigFilter" onchange="renderSignals()">
            <option value="ALL">كل الإشارات</option>
            <option value="BUY_STRONG">🚀 شراء قوي</option>
            <option value="BUY">📈 شراء</option>
            <option value="ACCUMULATE">📦 تجميع</option>
            <option value="WAIT">⏳ انتظار</option>
            <option value="AVOID">⚠️ تجنب</option>
            <option value="SELL">⬇️ بيع</option>
            <option value="SELL_STRONG">📉 بيع قوي</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">ترتيب حسب:</span>
          <select class="filter-select" id="sigSort" onchange="renderSignals()">
            <option value="score">الزخم</option>
            <option value="change">التغيير%</option>
            <option value="volume">الحجم</option>
            <option value="rsi">RSI</option>
          </select>
        </div>
        <span class="muted" id="sigCount" style="font-size:12px;margin-right:auto"></span>
      </div>
      <div class="table-wrap">
        <table id="sigTable">
          <thead>
            <tr>
              <th>الرمز</th>
              <th>السعر</th>
              <th>التغيير%</th>
              <th>الإشارة</th>
              <th>الزخم</th>
              <th>سعر الدخول</th>
              <th>وقف الخسارة</th>
              <th>الهدف الأول</th>
              <th>نسبة المخاطرة</th>
              <th>RSI</th>
              <th>حجم التداول</th>
            </tr>
          </thead>
          <tbody id="sigBody"></tbody>
        </table>
        <div class="pagination" id="sigPager"></div>
      </div>
    </div>

    <!-- ── Watchlist ── -->
    <div id="view-watchlist" class="view">
      <div id="watchlistContent"></div>
    </div>

    <!-- ── Market Overview ── -->
    <div id="view-market" class="view">
      <!-- حالة السوق -->
      <div class="kpi-row" id="marketKPIs" style="margin-bottom:16px"></div>
      <!-- Breadth + Entry Time -->
      <div id="breadthBar" style="margin-bottom:16px"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <!-- أعلى الرابحين -->
        <div class="info-section">
          <h3>🚀 أعلى الرابحين اليوم</h3>
          <div id="topGainers"></div>
        </div>
        <!-- أعلى الخاسرين -->
        <div class="info-section">
          <h3>📉 أعلى الخاسرين اليوم</h3>
          <div id="topLosers"></div>
        </div>
      </div>
      <!-- Heat Map القطاعات -->
      <div class="info-section" style="margin-top:16px">
        <h3>🌡️ Heat Map القطاعات</h3>
        <div id="sectorHeatmap"></div>
      </div>
    </div>

    <!-- ── Trades ── -->
    <div id="view-trades" class="view">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div>
          <div style="font-size:16px;font-weight:700">📋 متابعة صفقاتي</div>
          <div style="font-size:12px;color:var(--text-muted)">سجّل صفقاتك وتابع أداءها</div>
        </div>
        <div style="display:flex;gap:8px">
          <button onclick="exportTradesCSV()"
            style="background:rgba(99,179,237,0.1);border:1px solid rgba(99,179,237,0.3);
                   color:var(--accent-blue);padding:9px 16px;border-radius:10px;
                   cursor:pointer;font-family:Cairo,sans-serif;font-size:13px">
            📊 تصدير CSV
          </button>
          <button onclick="showAddTrade()"
            style="background:rgba(104,211,145,0.15);border:1px solid rgba(104,211,145,0.4);
                   color:var(--accent-green);padding:9px 18px;border-radius:10px;
                   cursor:pointer;font-family:Cairo,sans-serif;font-size:13px;font-weight:600">
            ➕ إضافة صفقة
          </button>
        </div>
      </div>
      <!-- ملخص الأداء -->
      <div class="kpi-row" id="tradesKPIs" style="margin-bottom:16px"></div>
      <!-- رسم بياني الأداء -->
      <div id="tradesChart" style="display:none;margin-bottom:16px"></div>
      <!-- جدول الصفقات -->
      <div class="table-wrap" id="tradesTable"></div>
    </div>

    <!-- ── Autopilot ── -->
    <div id="view-autopilot" class="view">

      <!-- إعدادات النظام -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
        <div class="info-section">
          <h3>⚙️ إعدادات الطيار الآلي</h3>
          <div style="display:flex;flex-direction:column;gap:10px" id="autoSettings">
            <div style="font-size:12px;color:var(--text-muted)">جاري التحميل...</div>
          </div>
          <button onclick="saveAutoSettings()"
            style="width:100%;margin-top:12px;background:rgba(179,122,237,0.15);
                   border:1px solid rgba(179,122,237,0.4);color:var(--accent-purple);
                   padding:9px;border-radius:8px;cursor:pointer;font-family:Cairo,sans-serif;font-size:13px">
            💾 حفظ الإعدادات
          </button>
        </div>
        <div class="info-section">
          <h3>📊 تحليل الأداء والتعلم</h3>
          <div id="perfAnalysis">
            <div style="font-size:12px;color:var(--text-muted)">جاري التحليل...</div>
          </div>
          <button onclick="loadPerformance()"
            style="margin-top:10px;background:rgba(99,179,237,0.1);border:1px solid var(--border);
                   color:var(--accent-blue);padding:7px 14px;border-radius:8px;
                   cursor:pointer;font-family:Cairo,sans-serif;font-size:12px">
            🔄 تحديث التحليل
          </button>
        </div>
      </div>

      <!-- سجل الإشارات التلقائية -->
      <div class="info-section">
        <h3 style="display:flex;align-items:center;justify-content:space-between">
          <span>📡 سجل الإشارات التلقائية</span>
          <div style="display:flex;gap:8px">
            <span id="autoEngineStatus" style="font-size:11px;padding:3px 10px;border-radius:10px;
              background:rgba(104,211,145,0.1);color:var(--accent-green)">● نشط</span>
            <button onclick="triggerTest()"
              style="background:rgba(246,224,94,0.1);border:1px solid rgba(246,224,94,0.3);
                     color:var(--accent-yellow);padding:3px 12px;border-radius:6px;
                     cursor:pointer;font-family:Cairo,sans-serif;font-size:11px">
              🧪 تشغيل اختبار
            </button>
            <button onclick="clearAutoLog()"
              style="background:none;border:1px solid var(--border);color:var(--text-muted);
                     padding:3px 10px;border-radius:6px;cursor:pointer;font-family:Cairo,sans-serif;font-size:11px">
              مسح السجل
            </button>
          </div>
        </h3>
        <div id="autoSignalsList"></div>
      </div>

    </div>

    <!-- ════════════════════════════════════════════════════════ -->
    <!-- View: Backtest (باك تيست) -->
    <!-- ════════════════════════════════════════════════════════ -->
    <div id="view-backtest" class="view">
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px" id="backtestStats">
        <div class="stat-card"><div class="stat-value" id="bt_total">0</div><div class="stat-label">إجمالي الإشارات</div></div>
        <div class="stat-card"><div class="stat-value" id="bt_winrate">0%</div><div class="stat-label">نسبة النجاح</div></div>
        <div class="stat-card"><div class="stat-value" id="bt_pnl">0</div><div class="stat-label">إجمالي P&L</div></div>
        <div class="stat-card"><div class="stat-value" id="bt_factor">0</div><div class="stat-label">Profit Factor</div></div>
      </div>
      <div class="info-section">
        <h3>📋 آخر الإشارات المغلقة</h3>
        <div style="font-size:12px;overflow-x:auto" id="backtestTable">
          <div style="padding:20px;text-align:center;color:var(--text-muted)">جاري التحميل...</div>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- Add Trade Modal -->
<div id="addTradeModal" class="modal-overlay" style="display:none" onclick="closeAddTrade(event)">
  <div class="modal" style="max-width:520px">
    <div class="modal-header">
      <div>
        <div class="modal-sym" style="font-size:20px">➕ إضافة صفقة جديدة</div>
        <div class="modal-name" id="addTradeSymInfo"></div>
      </div>
      <button class="modal-close" onclick="closeAddTrade()">✕</button>
    </div>
    <div class="modal-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">الرمز</label>
          <input id="trSym" class="filter-input" style="width:100%" placeholder="مثال: COMI"
            oninput="this.value=this.value.toUpperCase();fillTradeFromData(this.value)">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">سعر الدخول</label>
          <input id="trEntry" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">عدد الأسهم</label>
          <input id="trShares" class="filter-input" style="width:100%" type="number" placeholder="0"
            oninput="calcTradeTotal()">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">إجمالي الاستثمار</label>
          <div id="trTotal" style="font-family:Rajdhani,sans-serif;font-size:18px;font-weight:700;
               color:var(--accent-cyan);padding:7px 0">— ج</div>
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">🛑 وقف الخسارة</label>
          <input id="trStop" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">🎯 الهدف القريب 1</label>
          <input id="trNear1" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">🎯 الهدف القريب 2</label>
          <input id="trNear2" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">🎯 الهدف القريب 3</label>
          <input id="trNear3" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">🏆 الهدف البعيد 1</label>
          <input id="trT1" class="filter-input" style="width:100%" type="number" step="0.01" placeholder="0.00">
        </div>
      </div>
      <div style="margin-top:12px">
        <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">ملاحظات</label>
        <input id="trNotes" class="filter-input" style="width:100%" placeholder="أي ملاحظات على الصفقة...">
      </div>
      <button onclick="submitTrade()"
        style="width:100%;margin-top:16px;background:rgba(104,211,145,0.2);
               border:1px solid rgba(104,211,145,0.5);color:var(--accent-green);
               padding:12px;border-radius:10px;cursor:pointer;
               font-family:Cairo,sans-serif;font-size:14px;font-weight:700">
        ✅ تسجيل الصفقة
      </button>
    </div>
  </div>
</div>

<!-- Stock Detail Modal -->
<div id="stockModal" class="modal-overlay" style="display:none" onclick="closeModal(event)">
  <div class="modal" id="modalContent"></div>
</div>

<script>
// ══════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════
let ALL_DATA     = {};
let TOP_DATA     = [];
let FILTERED     = [];
let currentTab   = 'overview';
let overPage     = 1;
let screenerPage = 1;
let sigPage      = 1;
const PAGE_SIZE  = 30;
let sortCol  = 'score';
let sortDir  = -1;
let screenerFilter = 'ALL';
let watchlist = JSON.parse(localStorage.getItem('egx_watch') || '[]');

// ══════════════════════════════════════════════════════
// Init — polling حتى تيجي البيانات
// ══════════════════════════════════════════════════════
async function fetchWithTimeout(url, ms=25000, opts={}) {
  const ctrl = new AbortController();
  const tid  = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal });
    clearTimeout(tid);
    return r;
  } catch(e) {
    clearTimeout(tid);
    throw e.name === 'AbortError' ? new Error('انتهت مهلة الاتصال') : e;
  }
}

function setLoadingMsg(msg, sub) {
  const el = document.querySelector('.loading-text');
  if (el) el.innerHTML = msg + (sub ? `<br><span style="font-size:11px;color:#475569;margin-top:4px;display:block">${sub}</span>` : '');
}

function showLoadingError(msg) {
  document.getElementById('loadingOverlay').innerHTML = `
    <div style="text-align:center;padding:40px;max-width:420px">
      <div style="font-size:48px;margin-bottom:16px">⚠️</div>
      <div style="font-size:16px;font-weight:700;color:#fc8181;margin-bottom:12px">فشل تحميل البيانات</div>
      <div style="font-size:13px;color:#94a3b8;line-height:1.8;margin-bottom:20px">${msg}</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button onclick="location.reload()"
          style="background:rgba(99,179,237,0.15);border:1px solid rgba(99,179,237,0.4);
                 color:#63b3ed;padding:10px 20px;border-radius:10px;cursor:pointer;
                 font-family:Cairo,sans-serif;font-size:14px">
          🔄 إعادة المحاولة
        </button>
        <button onclick="openWithNoData()"
          style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);
                 color:#94a3b8;padding:10px 20px;border-radius:10px;cursor:pointer;
                 font-family:Cairo,sans-serif;font-size:14px">
          📂 فتح بدون بيانات
        </button>
      </div>
    </div>`;
}

function openWithNoData() {
  document.getElementById('loadingOverlay').style.display = 'none';
  document.getElementById('app').style.display = 'flex';
  document.getElementById('statusText').textContent = 'غير متصل — اضغط تحديث';
  renderAll();
}

async function init() {
  const MAX_WAIT_SEC = 120;
  const POLL_MS      = 2000;
  let   elapsed      = 0;

  setLoadingMsg('جاري الاتصال بالسيرفر...');
  await new Promise(r => setTimeout(r, 1000));

  while (elapsed < MAX_WAIT_SEC * 1000) {
    try {
      const r = await fetchWithTimeout('/api/ready', 4000);
      const j = await r.json();

      if (j.ready && j.count > 0) {
        // ── افتح التطبيق فوراً بدون انتظار loadAll ──
        document.getElementById('loadingOverlay').style.display = 'none';
        document.getElementById('app').style.display = 'flex';
        updateStatus(j.count, 0);

        // ── حمّل البيانات في الـ background ──
        loadAll()
          .then(() => loadTop())
          .then(() => {
            renderAll();
            loadTradesData();
            fetchMarket();
            fetchBreadth();
          })
          .catch(e => {
            console.error('Data load error:', e);
            setTimeout(() => loadAll().then(() => loadTop()).then(() => renderAll()), 3000);
          });
        return;
      } else {
        const secs = Math.round(elapsed / 1000);
        setLoadingMsg(
          'جاري تحميل بيانات البورصة المصرية...',
          `يتم جلب البيانات من TradingView — ${secs} ث`
        );
      }
    } catch(e) {
      setLoadingMsg('جاري الاتصال...', e.message);
    }

    await new Promise(r => setTimeout(r, POLL_MS));
    elapsed += POLL_MS;
  }

  showLoadingError(`
    استغرق التحميل أكثر من ${MAX_WAIT_SEC} ثانية.<br><br>
    تأكد من:<br>
    <ul style="text-align:right;margin:8px 0;padding-right:20px;line-height:2">
      <li>الاتصال بالإنترنت شغال</li>
      <li>موقع TradingView مش محجوب</li>
      <li>مفيش Firewall أو VPN بيمنع الاتصال</li>
    </ul>
  `);
}


async function loadAll() {
  const r = await fetchWithTimeout('/api/all', 45000);
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || 'خطأ في الـ API');
  ALL_DATA = j.data || {};
  updateStatus(j.count, j.age_sec);
}

async function loadTop() {
  try {
    const r = await fetchWithTimeout('/api/top', 15000);
    const j = await r.json();
    if (j.ok) TOP_DATA = j.top || [];
  } catch(e) { TOP_DATA = []; }
}

function updateStatus(count, age) {
  document.getElementById('statusText').textContent =
    `${count} سهم | آخر تحديث: ${Math.round(age)} ث`;
}

async function doRefresh() {
  const btn = document.getElementById('btnRefresh');
  btn.classList.add('loading');
  btn.innerHTML = '<span>⏳</span> جاري...';
  try {
    await fetchWithTimeout('/api/refresh', 5000).catch(()=>{});
    await loadAll();
    await loadTop();
    _marketData  = null;
    _breadthData = null;
    renderAll();
    loadTradesData();
    fetchMarket();
    fetchBreadth();
    fetchBreadth();
    if (currentTab === 'market') renderMarket();
    if (currentTab === 'trades') renderTrades();
  } catch(e) {
    alert('فشل التحديث: ' + e.message);
  }
  btn.classList.remove('loading');
  btn.innerHTML = '<span>🔄</span> تحديث';
}

// ══════════════════════════════════════════════════════
// Tab switching
// ══════════════════════════════════════════════════════
// switchTab is defined below (full version with all tabs including autopilot)

// ══════════════════════════════════════════════════════
// renderAll
// ══════════════════════════════════════════════════════
function renderAll() {
  renderKPIs();
  renderOverview();
  renderSectorBars();
  renderSignalDist();
  renderOpportunities();
  // badge يعرض عدد الفرص المفلترة الفعلية
  const filteredCount = FILTERED.length || TOP_DATA.length;
  document.getElementById('badgeOpps').textContent = filteredCount;
  document.getElementById('badgeWatch').textContent = watchlist.length;
}

// ══════════════════════════════════════════════════════
// KPIs
// ══════════════════════════════════════════════════════
function renderKPIs() {
  const stocks = Object.values(ALL_DATA);
  const total  = stocks.length;
  const gainers = stocks.filter(s => (s.change_pct||0) > 0).length;
  const losers  = stocks.filter(s => (s.change_pct||0) < 0).length;
  const buys    = stocks.filter(s => s.analysis?.signal_type?.startsWith('BUY')).length;
  const sells   = stocks.filter(s => s.analysis?.signal_type?.startsWith('SELL')).length;
  const avgRSI  = avg(stocks.map(s => s.rsi).filter(Boolean));
  const bigVol  = stocks.filter(s => {
    const v = s.volume || 0, a = s.avg_vol || 1;
    return v / a >= 2;
  }).length;

  const kpis = [
    { label:'إجمالي الأسهم',   value: total,            sub:'مسجل في EGX',         color:'var(--accent-blue)' },
    { label:'أسهم صاعدة',      value: gainers,           sub:`${pct(gainers,total)}%`, color:'var(--accent-green)' },
    { label:'أسهم هابطة',      value: losers,            sub:`${pct(losers,total)}%`,  color:'var(--accent-red)' },
    { label:'إشارات شراء',     value: buys,              sub:'فرص محتملة',           color:'var(--buy)' },
    { label:'إشارات بيع',      value: sells,             sub:'تحذيرات',              color:'var(--sell)' },
    { label:'متوسط RSI',       value: avgRSI.toFixed(1), sub: avgRSI < 40 ? 'تشبع بيع ⚠' : avgRSI > 60 ? 'تشبع شراء ⚠' : 'محايد ✓', color:'var(--accent-cyan)' },
    { label:'حجم استثنائي',    value: bigVol,            sub:'حجم > 2× المتوسط',    color:'var(--accent-yellow)' },
  ];
  document.getElementById('kpiRow').innerHTML = kpis.map(k => `
    <div class="kpi-card">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value" style="color:${k.color}">${fmt(k.value)}</div>
      <div class="kpi-sub">${k.sub}</div>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════
// Overview Table
// ══════════════════════════════════════════════════════
function getOverviewData() {
  const search = (document.getElementById('overSearch')?.value||'').toLowerCase();
  const sector = document.getElementById('overSector')?.value || '';
  const signal = document.getElementById('overSignal')?.value || '';
  
  return Object.entries(ALL_DATA).filter(([sym, s]) => {
    if (search && !sym.toLowerCase().includes(search) &&
        !(s.name_en||'').toLowerCase().includes(search) &&
        !(s.tv_name||'').toLowerCase().includes(search)) return false;
    if (sector && s.sector !== sector) return false;
    if (signal && s.analysis?.signal_type !== signal) return false;
    return true;
  }).sort((a,b) => {
    const va = getSortVal(a, sortCol);
    const vb = getSortVal(b, sortCol);
    return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
  });
}

function getSortVal([sym,s], col) {
  switch(col) {
    case 'sym':    return sym;
    case 'price':  return s.price || 0;
    case 'change': return s.change_pct || 0;
    case 'signal': return s.analysis?.score || 0;
    case 'score':  return s.analysis?.score || 0;
    case 'rsi':    return s.rsi || 0;
    case 'volume': return s.volume || 0;
    case 'vs_egx30': return s.analysis?.vs_egx30 ?? -999;
    case 'sector': return s.sector || '';
    default:       return 0;
  }
}

function renderOverview() {
  const data = getOverviewData();
  document.getElementById('overCount').textContent = `${data.length} سهم`;
  
  // Populate sector filter
  const secs = [...new Set(Object.values(ALL_DATA).map(s => s.sector).filter(Boolean))].sort();
  const secSel = document.getElementById('overSector');
  if (secSel.options.length <= 1) {
    secs.forEach(s => { const o = document.createElement('option'); o.value=s; o.text=s; secSel.add(o); });
  }
  
  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  if (overPage > totalPages) overPage = 1;
  const slice = data.slice((overPage-1)*PAGE_SIZE, overPage*PAGE_SIZE);
  
  document.getElementById('overBody').innerHTML = slice.map(([sym, s]) => {
    const a   = s.analysis || {};
    const chg = s.change_pct || 0;
    const star = watchlist.includes(sym) ? '⭐' : '☆';
    return `<tr onclick="openModal('${sym}')">
      <td><b style="color:var(--accent-blue)">${sym}</b><br><span style="font-size:10px;color:var(--text-muted)">${s.tv_name||''}</span></td>
      <td style="font-family:Rajdhani,sans-serif;font-size:15px;font-weight:700">${fmt(s.price)}</td>
      <td class="${chg>=0?'green':'red'}" style="font-family:Rajdhani,sans-serif">${chg>=0?'+':''}${chg}%</td>
      <td>${sigBadge(a.signal, a.signal_color, a.signal_emoji)}</td>
      <td>${scoreBar(a.score)}</td>
      <td>${rsiCell(s.rsi)}</td>
      <td style="font-size:11px">${volCell(s.volume, s.avg_vol, a.vol_class)}</td>
      <td style="font-size:11px">${adxBadge(s.adx, a.adx_label)}</td>
      <td style="font-size:11px">${vsEgx30Cell(a.vs_egx30)}</td>
      <td style="font-size:11px;color:var(--text-muted)">${s.sector||''}</td>
      <td onclick="event.stopPropagation();toggleWatch('${sym}')" style="cursor:pointer;font-size:16px">${star}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="9"><div class="empty-state"><div class="empty-icon">🔍</div>لا توجد نتائج</div></td></tr>`;
  
  renderPager('overPager', overPage, totalPages, p => { overPage=p; renderOverview(); });
}

function sortTable(col) {
  if (sortCol === col) sortDir *= -1; else { sortCol = col; sortDir = -1; }
  overPage = 1;
  renderOverview();
}

// ══════════════════════════════════════════════════════
// Sector Bars
// ══════════════════════════════════════════════════════
function renderSectorBars() {
  const counts = {};
  Object.values(ALL_DATA).forEach(s => {
    const sec = s.sector || 'أخرى';
    counts[sec] = (counts[sec] || 0) + 1;
  });
  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]).slice(0,10);
  const max    = sorted[0]?.[1] || 1;
  document.getElementById('sectorBars').innerHTML = sorted.map(([sec, cnt]) => `
    <div class="sector-bar-row">
      <div class="sector-name">${sec}</div>
      <div class="sector-bar-track">
        <div class="sector-bar-fill" style="width:${pct(cnt,max)}%"></div>
      </div>
      <div class="sector-count">${cnt}</div>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════
// Signal Distribution
// ══════════════════════════════════════════════════════
function renderSignalDist() {
  const types = {
    'BUY_STRONG': {label:'شراء قوي',  color:'var(--buy-strong)', emoji:'🚀'},
    'BUY':        {label:'شراء',      color:'var(--buy)',         emoji:'📈'},
    'ACCUMULATE': {label:'تجميع',     color:'var(--accumulate)', emoji:'📦'},
    'WAIT':       {label:'انتظار',    color:'var(--wait)',       emoji:'⏳'},
    'AVOID':      {label:'تجنب',      color:'var(--avoid)',      emoji:'⚠️'},
    'SELL':       {label:'بيع',       color:'var(--sell)',       emoji:'⬇️'},
    'SELL_STRONG':{label:'بيع قوي',  color:'var(--sell-strong)','emoji':'📉'},
  };
  const counts = {};
  Object.values(ALL_DATA).forEach(s => {
    const t = s.analysis?.signal_type || 'WAIT';
    counts[t] = (counts[t]||0) + 1;
  });
  const total = Object.values(counts).reduce((a,b)=>a+b,0) || 1;
  document.getElementById('signalDist').innerHTML = Object.entries(types).map(([k, info]) => {
    const cnt = counts[k] || 0;
    return `
    <div class="sector-bar-row" style="margin-bottom:6px">
      <div class="sector-name" style="font-size:12px;color:var(--text-primary)">
        ${info.emoji} ${info.label}
      </div>
      <div class="sector-bar-track">
        <div class="sector-bar-fill" style="width:${pct(cnt,total)}%;background:${info.color}"></div>
      </div>
      <div class="sector-count">${cnt}</div>
    </div>`;
  }).join('');
}

// ══════════════════════════════════════════════════════
// Top Opportunities
// ══════════════════════════════════════════════════════
function renderOpportunities() {
  // تطبيق فلاتر رأس المال والجودة
  const capital    = parseFloat(document.getElementById('capitalInput')?.value) || 0;
  const minQuality = parseFloat(document.getElementById('minQualityFilter')?.value) || 0;
  const sigFilter  = document.getElementById('oppSignalFilter')?.value || '';

  FILTERED = TOP_DATA.filter(t => {
    if (minQuality && (t.trade_quality||0) < minQuality) return false;
    if (sigFilter  && t.signal_type !== sigFilter) return false;
    // فلترة رأس المال: لو السعر × أقل كمية ممكنة (10 أسهم) > رأس المال، استبعد
    if (capital && t.entry && capital < t.entry * 10) return false;
    return true;
  });

  // عدد الأسهم الممكن شراؤها بالرأس المال
  if (capital) {
    FILTERED.forEach(t => {
      t._max_shares = t.entry ? Math.floor(capital / t.entry) : 0;
    });
  }

  const readyCount  = FILTERED.filter(t => t.ready).length;
  const nearCount   = FILTERED.filter(t => !t.ready && (t.proximity||0) >= 70).length;
  const strongCount = FILTERED.filter(t => t.signal_type === 'BUY_STRONG').length;
  const accumCount  = FILTERED.filter(t => t.signal_type === 'ACCUMULATE').length;
  document.getElementById('oppFilterCount').textContent =
    `${FILTERED.length} فرصة${capital ? ` | رأس المال: ${capital.toLocaleString()} ج` : ''}`;

  document.getElementById('oppStats').innerHTML = [
    { icon:'✅', num:readyCount,        desc:'جاهزة للدخول الآن',   color:'var(--buy-strong)',  tip:'السعر داخل نطاق الدخول' },
    { icon:'🎯', num:nearCount,         desc:'قريبة من نطاق الدخول', color:'var(--accumulate)', tip:'قرب >= 70%' },
    { icon:'🚀', num:strongCount,       desc:'شراء قوي',             color:'var(--buy)',         tip:'' },
    { icon:'📦', num:accumCount,        desc:'تجميع',                color:'var(--accent-yellow)', tip:'' },
    { icon:'📊', num:FILTERED.length,   desc:'إجمالي الفرص المعروضة', color:'var(--accent-blue)', tip:'R:R≥1.5 + سيولة كافية' },
  ].map(x => `
    <div class="stat-card" ${x.tip ? `data-tip="${x.tip}"` : ''}>
      <div class="stat-icon">${x.icon}</div>
      <div class="stat-info">
        <div class="stat-num" style="color:${x.color}">${x.num}</div>
        <div class="stat-desc">${x.desc}</div>
      </div>
    </div>`).join('');

  document.getElementById('topGrid').innerHTML = FILTERED.map(t => {
    const chg  = t.change_pct || 0;
    const rr1  = t.rr1 || t.rr?.[0] || 0;
    const tq   = t.trade_quality || 0;
    const prox = t.proximity || 0;
    const liq  = t.liq_score || 0;

    // ready badge
    let readyBadge;
    const scenario = t.entry_scenario || 'WAIT';
    if (scenario === 'MARKET' || t.ready) {
      readyBadge = `<span class="ready-badge ready">✅ ادخل الآن بسعر السوق</span>`;
    } else if (scenario === 'NEAR' || prox >= 70) {
      const distPct = t.entry ? ((t.price - t.entry)/t.price*100).toFixed(1) : prox.toFixed(0);
      readyBadge = `<span class="ready-badge near">🎯 قريب — السعر فوق الدخول بـ ${distPct}%</span>`;
    } else {
      const distPct = t.entry ? ((t.price - t.entry)/t.entry*100).toFixed(1) : '';
      readyBadge = `<span class="ready-badge waiting">⏳ استنى — الدخول أدنى بـ ${distPct}%</span>`;
    }

    // quality ring color
    const qColor = tq >= 80 ? '#00e676' : tq >= 60 ? '#f6e05e' : tq >= 40 ? '#63b3ed' : '#94a3b8';

    // liquidity dots
    const liqDots = liq >= 80 ? '💧💧💧' : liq >= 60 ? '💧💧' : liq >= 40 ? '💧' : '⚠️';

    return `
    <div class="top-card ${t.signal_type}" onclick="openModal('${t.symbol}')">
      <div class="top-card-header">
        <div>
          <div class="top-card-sym">${t.symbol}</div>
          <div class="top-card-name" style="font-size:10px;color:var(--text-muted)">${t.name||''}</div>
          <div style="margin-top:4px">${readyBadge}</div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
          <div class="quality-ring" style="border-color:${qColor};color:${qColor}" data-tip="جودة الصفقة (R:R × سيولة × قرب)">
            ${tq.toFixed(0)}
          </div>
          <div style="font-size:10px;color:var(--text-muted);text-align:center">جودة</div>
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0 4px">
        <div>
          <span style="font-family:Rajdhani,sans-serif;font-size:20px;font-weight:700">${fmt(t.price)}</span>
          <span style="font-size:11px;color:var(--text-muted)"> ج</span>
        </div>
        <span class="${chg>=0?'green':'red'}" style="font-size:13px">${chg>=0?'+':''}${chg}%</span>
        <div>${sigBadge(t.signal, t.signal_color || '', '')}</div>
      </div>

      <!-- Entry Zone -->
      <div class="top-card-entry-zone">
        ${t._max_shares ? `<div class="tez-row" style="margin-bottom:4px">
          <span class="tez-label">💰 بـ ${capital.toLocaleString()} ج</span>
          <span class="tez-val cyan">${t._max_shares} سهم</span>
        </div>` : ''}
        <div class="tez-row">
          <span class="tez-label">📍 الدخول المثالي</span>
          <span class="tez-val cyan">${fmt(t.entry)}
            ${scenario==='MARKET'?'<span style="font-size:9px;color:var(--accent-green)"> ← الآن</span>':
              scenario==='NEAR'?'<span style="font-size:9px;color:var(--accent-yellow)"> ← قريب</span>':
              '<span style="font-size:9px;color:var(--text-muted)"> ← استنى</span>'}
          </span>
        </div>
        <div class="tez-row">
          <span class="tez-label">نطاق الدخول</span>
          <span class="tez-val" style="font-size:11px;color:var(--text-secondary)">${fmt(t.entry_low)} ← ${fmt(t.entry_high)}</span>
        </div>
        <div class="tez-row">
          <span class="tez-label">🛑 وقف الخسارة</span>
          <span class="tez-val red">${fmt(t.stop)} <span style="font-size:10px;opacity:0.7">(${t.risk_pct||0}%)</span></span>
        </div>
        <div class="tez-row" style="margin-bottom:0">
          <span class="tez-label">🎯 الهدف القريب 1</span>
          <span class="tez-val green">${fmt(t.near_targets?.[0])} <span class="cyan" style="font-size:10px">+${t.near_pcts?.[0]||0}%</span></span>
        </div>
        <div class="tez-row" style="margin-bottom:0;margin-top:2px">
          <span class="tez-label">🎯 الهدف القريب 2</span>
          <span class="tez-val green">${fmt(t.near_targets?.[1])} <span class="cyan" style="font-size:10px">+${t.near_pcts?.[1]||0}%</span></span>
        </div>
      </div>

      <!-- Bottom metrics -->
      <div class="top-card-quality">
        <div style="flex:1;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">RSI</div>
          <div class="metric-val ${(t.rsi||50)<30?'green':(t.rsi||50)>70?'red':''}" style="font-family:Rajdhani,sans-serif;font-weight:700">${t.rsi||'—'}</div>
        </div>
        <div style="flex:1;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">ADX</div>
          <div style="font-size:11px">${t.adx ? adxBadge(t.adx, t.adx_label) : '—'}</div>
        </div>
        <div style="flex:1;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">سيولة</div>
          <div style="font-size:13px">${liqDots}</div>
        </div>
        <div style="flex:1;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">حجم</div>
          <div style="font-size:11px;color:var(--text-secondary)">${t.vol_class||'—'}</div>
        </div>
      </div>
      ${t.candle ? `<div style="font-size:11px;padding:5px 8px;margin-top:4px;border-radius:6px;
        background:${t.candle.type==='BULLISH'?'rgba(104,211,145,0.08)':t.candle.type==='BEARISH'?'rgba(252,129,129,0.08)':'rgba(255,255,255,0.04)'};
        border:1px solid ${t.candle.type==='BULLISH'?'rgba(104,211,145,0.2)':t.candle.type==='BEARISH'?'rgba(252,129,129,0.2)':'rgba(255,255,255,0.08)'}">
        🕯 ${t.candle.ar}
      </div>` : ''}
      ${t.engine_ready ? `<div style="font-size:11px;padding:4px 8px;margin-top:4px;border-radius:6px;background:rgba(179,122,237,0.1);border:1px solid rgba(179,122,237,0.3);display:flex;align-items:center;gap:5px">
        🤖 <b style="color:var(--accent-purple)">جاهز للطيار الآلي</b>
      </div>` : ''}
      ${t.confirmation?.bull_count >= 3 ? `<div style="font-size:11px;padding:4px 8px;margin-top:4px;border-radius:6px;background:rgba(0,230,118,0.06);border:1px solid rgba(0,230,118,0.15)">
        ✅ تأكيد: ${t.confirmation.label} (${t.confirmation.bull_count} مؤشر)
      </div>` : ''}
      ${t.divergences?.length ? `<div class="div-badge div-${t.divergences[0].type==='BULLISH'?'bull':'bear'}" style="margin-top:4px;font-size:10px">
        ${t.divergences[0].ar}
      </div>` : ''}
      ${(t.resistance_info?.near_resistance) ? `<div style="font-size:10px;padding:3px 8px;margin-top:4px;border-radius:6px;background:rgba(246,173,85,0.08);color:var(--accent-orange)">
        ${t.resistance_info.warning}
      </div>` : ''}
      ${capital && t._max_shares && t.position_data ? (() => {
        const riskPct = parseFloat(document.getElementById('riskPctSelect')?.value||2);
        const rpe = t.position_data.risk_per_share || 0.01;
        const maxRisk = capital * riskPct / 100;
        const optShares = Math.min(t._max_shares, Math.floor(maxRisk / rpe));
        const optCost = (optShares * (t.entry||0)).toFixed(0);
        return optShares > 0 ? `<div style="font-size:11px;padding:4px 8px;margin-top:4px;border-radius:6px;background:rgba(99,179,237,0.06);border:1px solid rgba(99,179,237,0.15)">
          💰 الكمية المثالية: <b>${optShares} سهم</b> = ${optCost} ج (مخاطرة ${riskPct}%)
        </div>` : '';
      })() : ''}
    </div>`;
  }).join('') || '<div class="empty-state"><div class="empty-icon">📊</div><p>لا توجد فرص مؤهلة (R:R ≥ 1.5 + سيولة كافية)</p></div>';
}

// ══════════════════════════════════════════════════════
// Screener
// ══════════════════════════════════════════════════════
function applyScreener(filter, el) {
  screenerFilter = filter;
  screenerPage = 1;
  document.querySelectorAll('.screener-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  renderScreener();
}

function renderScreener() {
  const stocks = Object.entries(ALL_DATA).filter(([sym, s]) => {
    switch(screenerFilter) {
      case 'RSI_OVERSOLD':   return (s.rsi||50) < 30;
      case 'RSI_OVERBOUGHT': return (s.rsi||50) > 70;
      case 'HIGH_VOL':       return (s.volume||0) / (s.avg_vol||1) >= 2;
      case 'NEAR_52H':       return s.high52w && s.price && (s.high52w - s.price) / s.high52w < 0.05;
      case 'NEAR_52L':       return s.low52w  && s.price && (s.price - s.low52w)  / s.price  < 0.05;
      case 'ABOVE_SMA200':   return s.price && s.sma200 && s.price > s.sma200;
      case 'GOLDEN_CROSS':   return s.sma20 && s.sma50 && s.sma20 > s.sma50;
      case 'BB_SQUEEZE':     return s.analysis?.bb_pos_pct !== null && s.analysis?.bb_pos_pct !== undefined;
      default: return true;
    }
  });

  const total = Math.ceil(stocks.length / PAGE_SIZE);
  if (screenerPage > total) screenerPage = 1;
  const slice = stocks.slice((screenerPage-1)*PAGE_SIZE, screenerPage*PAGE_SIZE);

  document.getElementById('screenerBody').innerHTML = slice.map(([sym, s]) => {
    const a   = s.analysis || {};
    const chg = s.change_pct || 0;
    const relV = s.avg_vol ? ((s.volume||0)/s.avg_vol).toFixed(1) : '—';
    const macdStr = s.macd !== null && s.macd !== undefined ?
      `<span class="${s.macd > s.macd_signal ? 'green':'red'}">${s.macd?.toFixed(3)||'—'}</span>` : '—';
    return `<tr onclick="openModal('${sym}')">
      <td><b style="color:var(--accent-blue)">${sym}</b></td>
      <td style="font-family:Rajdhani,sans-serif;font-weight:700">${fmt(s.price)}</td>
      <td class="${chg>=0?'green':'red'}">${chg>=0?'+':''}${chg}%</td>
      <td>${rsiCell(s.rsi)}</td>
      <td>${macdStr}</td>
      <td style="font-family:Rajdhani,sans-serif">${s.adx?.toFixed(1)||'—'}</td>
      <td>${a.bb_pos_pct !== null && a.bb_pos_pct !== undefined ? a.bb_pos_pct+'%' : '—'}</td>
      <td style="font-size:11px">${fmt(s.sma20)}</td>
      <td style="font-size:11px">${fmt(s.sma200)}</td>
      <td><span class="${relV>=2?'yellow':relV>=1.5?'cyan':''}">${relV}x</span></td>
      <td class="${(s.perf_1m||0)>=0?'green':'red'}">${s.perf_1m ? parseFloat(s.perf_1m).toFixed(1)+'%' : '—'}</td>
      <td>${sigBadge(a.signal, a.signal_color, a.signal_emoji)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="12"><div class="empty-state"><div class="empty-icon">🔍</div>لا توجد نتائج</div></td></tr>';

  renderPager('screenerPager', screenerPage, total, p => { screenerPage=p; renderScreener(); });
}

// ══════════════════════════════════════════════════════
// Signals
// ══════════════════════════════════════════════════════
function renderSignals() {
  const filter = document.getElementById('sigFilter')?.value || 'ALL';
  const sortBy = document.getElementById('sigSort')?.value || 'score';

  let stocks = Object.entries(ALL_DATA).filter(([sym, s]) => {
    const st = s.analysis?.signal_type || 'WAIT';
    return filter === 'ALL' || st === filter;
  });

  stocks.sort((a, b) => {
    const sa = a[1], sb = b[1];
    switch(sortBy) {
      case 'change': return (sb.change_pct||0) - (sa.change_pct||0);
      case 'volume': return (sb.volume||0) - (sa.volume||0);
      case 'rsi':    return (sa.rsi||50) - (sb.rsi||50);
      default:       return (sb.analysis?.score||0) - (sa.analysis?.score||0);
    }
  });

  document.getElementById('sigCount').textContent = `${stocks.length} إشارة`;
  const total = Math.ceil(stocks.length / PAGE_SIZE);
  if (sigPage > total) sigPage = 1;
  const slice = stocks.slice((sigPage-1)*PAGE_SIZE, sigPage*PAGE_SIZE);

  document.getElementById('sigBody').innerHTML = slice.map(([sym, s]) => {
    const a   = s.analysis || {};
    const t   = a.trade || {};
    const chg = s.change_pct || 0;
    const rr  = t.rr_ratios?.[0];
    return `<tr onclick="openModal('${sym}')">
      <td><b style="color:var(--accent-blue)">${sym}</b></td>
      <td style="font-family:Rajdhani,sans-serif;font-weight:700">${fmt(s.price)}</td>
      <td class="${chg>=0?'green':'red'}">${chg>=0?'+':''}${chg}%</td>
      <td>${sigBadge(a.signal, a.signal_color, a.signal_emoji)}</td>
      <td>${scoreBar(a.score)}</td>
      <td style="color:var(--accent-cyan);font-family:Rajdhani,sans-serif">${fmt(t.entry_ideal)}</td>
      <td style="color:var(--accent-red);font-family:Rajdhani,sans-serif">${fmt(t.stop_loss)}</td>
      <td style="color:var(--accent-green);font-family:Rajdhani,sans-serif">${fmt(t.targets?.[0])}</td>
      <td><span class="${rr>=2?'green':rr>=1?'yellow':'red'}">${rr ? rr+'x' : '—'}</span></td>
      <td>${rsiCell(s.rsi)}</td>
      <td style="font-size:11px">${a.vol_class||'—'}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="11"><div class="empty-state"><div class="empty-icon">📡</div>لا توجد إشارات</div></td></tr>';

  renderPager('sigPager', sigPage, total, p => { sigPage=p; renderSignals(); });
}

// ══════════════════════════════════════════════════════
// Watchlist
// ══════════════════════════════════════════════════════
function toggleWatch(sym) {
  const idx = watchlist.indexOf(sym);
  if (idx >= 0) watchlist.splice(idx, 1);
  else watchlist.push(sym);
  localStorage.setItem('egx_watch', JSON.stringify(watchlist));
  document.getElementById('badgeWatch').textContent = watchlist.length;
  renderOverview();
  if (currentTab === 'watchlist') renderWatchlist();
}

function renderWatchlist() {
  const el = document.getElementById('watchlistContent');
  if (!watchlist.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">⭐</div><p>قائمة المتابعة فارغة. اضغط على ☆ بجانب أي سهم لإضافته.</p></div>';
    return;
  }
  const stocks = watchlist.map(sym => [sym, ALL_DATA[sym]]).filter(([,s]) => s);
  el.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>الرمز</th><th>السعر</th><th>التغيير%</th><th>الإشارة</th>
          <th>الزخم</th><th>RSI</th><th>الدخول المثالي</th><th>وقف الخسارة</th><th>الهدف 1</th><th>إزالة</th>
        </tr></thead>
        <tbody>${stocks.map(([sym, s]) => {
          const a = s.analysis||{}, t = a.trade||{}, chg = s.change_pct||0;
          return `<tr onclick="openModal('${sym}')">
            <td><b style="color:var(--accent-blue)">${sym}</b></td>
            <td style="font-family:Rajdhani,sans-serif;font-weight:700">${fmt(s.price)}</td>
            <td class="${chg>=0?'green':'red'}">${chg>=0?'+':''}${chg}%</td>
            <td>${sigBadge(a.signal, a.signal_color, a.signal_emoji)}</td>
            <td>${scoreBar(a.score)}</td>
            <td>${rsiCell(s.rsi)}</td>
            <td style="color:var(--accent-cyan)">${fmt(t.entry_ideal)}</td>
            <td style="color:var(--accent-red)">${fmt(t.stop_loss)}</td>
            <td style="color:var(--accent-green)">${fmt(t.targets?.[0])}</td>
            <td onclick="event.stopPropagation();toggleWatch('${sym}')" style="cursor:pointer;color:var(--accent-red)">✕</td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>`;
}

// ══════════════════════════════════════════════════════
// Stock Modal
// ══════════════════════════════════════════════════════
async function openModal(sym) {
  const s = ALL_DATA[sym];
  if (!s) return;
  const a   = s.analysis || {};
  const t   = a.trade    || {};
  const fib = a.fib      || {};
  const piv = a.pivots   || {};
  const chg = s.change_pct || 0;

  const html = `
  <div class="modal-header">
    <div>
      <div class="modal-sym">${sym}</div>
      <div class="modal-name">${s.tv_name||''} | ${s.sector||''}</div>
    </div>
    <div style="margin-right:20px">
      <div class="modal-price">${fmt(s.price)} <span style="font-size:14px;color:var(--text-muted)">ج.م</span></div>
      <div class="modal-change ${chg>=0?'green':'red'}">${chg>=0?'+':''}${chg}% (${fmt(s.change_abs)})</div>
    </div>
    <div style="margin-right:20px">
      ${sigBadge(a.signal, a.signal_color, a.signal_emoji, 'large')}
      <div style="text-align:center;margin-top:6px">
        <span style="font-family:Rajdhani,sans-serif;font-size:28px;font-weight:700;color:${scoreColor(a.score)}">${a.score||0}</span>
        <span style="font-size:11px;color:var(--text-muted)">/100</span>
      </div>
    </div>
      <button onclick="addTradeFromModal(sym)"
        style="background:rgba(104,211,145,0.1);border:1px solid rgba(104,211,145,0.3);
               color:var(--accent-green);padding:6px 14px;border-radius:8px;
               cursor:pointer;font-family:Cairo,sans-serif;font-size:12px">
        ➕ سجّل صفقة
      </button>
    <button class="modal-close" onclick="closeModal()">✕</button>
  </div>
  <div class="modal-body">
    <div class="modal-grid">

      <!-- Market Data -->
      <div class="info-section">
        <h3>📊 بيانات السوق</h3>
        ${infoRow('فتح اليوم',    fmt(s.open_p))}
        ${infoRow('أعلى اليوم',   fmt(s.day_high), 'green')}
        ${infoRow('أدنى اليوم',   fmt(s.day_low),  'red')}
        ${infoRow('أعلى 52 أسبوع', fmt(s.high52w), 'green')}
        ${infoRow('أدنى 52 أسبوع', fmt(s.low52w),  'red')}
        ${infoRow('حجم التداول',   fmtVol(s.volume))}
        ${infoRow('متوسط الحجم 30 يوم', fmtVol(s.avg_vol))}
        ${infoRow('تصنيف الحجم',  a.vol_class||'—')}
      </div>

      <!-- Technical Indicators -->
      <div class="info-section">
        <h3>📈 المؤشرات الفنية</h3>
        ${infoRow('RSI (14)',      rsiCell(s.rsi))}
        ${infoRow('MACD',         s.macd !== null ? `<span class="${(s.macd||0)>(s.macd_signal||0)?'green':'red'}">${(s.macd||0).toFixed(3)}</span>` : '—')}
        ${infoRow('Stochastic K', s.stoch_k?.toFixed(1)||'—')}
        ${infoRow('ADX',          s.adx?.toFixed(1) ? `<span class="${s.adx>25?'green':'muted'}">${s.adx.toFixed(1)}</span>` : '—')}
        ${infoRow('ATR',          fmt(s.atr))}
        ${infoRow('بولينجر %',   a.bb_pos_pct !== null ? a.bb_pos_pct+'%' : '—')}
        ${infoRow('SMA20/50/200', `${fmt(s.sma20)} / ${fmt(s.sma50)} / ${fmt(s.sma200)}`)}
        ${infoRow('التوصية TV',   s.rating||'—')}
      </div>

      <!-- Fundamental -->
      <div class="info-section">
        <h3>💰 البيانات الأساسية</h3>
        ${infoRow('القيمة السوقية', fmtCap(s.market_cap))}
        ${infoRow('ربحية السهم EPS', fmt(s.pe))}
        ${infoRow('عائد الأرباح', s.div_yield ? (s.div_yield*100).toFixed(2)+'%' : '—')}
        ${infoRow('القطاع',       s.sector||'—')}
        ${infoRow('الصناعة',      s.industry||'—')}
      </div>

      <!-- Performance -->
      <div class="info-section">
        <h3>📅 الأداء التاريخي</h3>
        ${infoRow('أسبوعي',    perfCell(s.perf_w))}
        ${infoRow('شهري',      perfCell(s.perf_1m))}
        ${infoRow('3 أشهر',    perfCell(s.perf_3m))}
        ${infoRow('6 أشهر',    perfCell(s.perf_6m))}
        ${infoRow('سنوي',      perfCell(s.perf_y))}
        ${infoRow('بعد أعلى 52أ', a.dist_from_high ? '-'+a.dist_from_high+'%' : '—', 'red')}
        ${infoRow('فوق أدنى 52أ', a.dist_from_low  ? '+'+a.dist_from_low+'%'  : '—', 'green')}
      </div>

      <!-- Trade Plan -->
      <div class="trade-plan">
        <h3>🎯 خطة التداول المقترحة
          <span style="margin-right:auto;font-size:12px;font-weight:400;color:var(--text-secondary)">${t.quality_label||''}</span>
        </h3>

        <!-- جودة الصفقة + السيولة -->
        <div style="display:flex;gap:12px;margin-bottom:14px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:10px;background:var(--bg-card);border-radius:8px;padding:8px 12px;flex:1;min-width:200px">
            <div class="quality-ring" style="border-color:${qualColor(t.trade_quality)};color:${qualColor(t.trade_quality)}"
                 data-tip="جودة الصفقة = (R:R × 40%) + (سيولة × 30%) + (قرب الدخول × 30%)">
              ${Math.round(t.trade_quality||0)}
            </div>
            <div>
              <div style="font-size:12px;font-weight:600">${t.quality_label||'—'}</div>
              <div style="font-size:10px;color:var(--text-muted)">جودة الصفقة / 100</div>
            </div>
          </div>
          <div style="background:var(--bg-card);border-radius:8px;padding:8px 12px;flex:1;min-width:200px">
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">السيولة والتنفيذ</div>
            <div class="liq-bar-wrap">
              <div class="liq-track" style="flex:1">
                <div class="liq-fill" style="width:${t.liq_score||0}%;background:${liqColor(t.liq_score||0)}"></div>
              </div>
              <span style="font-family:Rajdhani,sans-serif;font-size:12px;color:${liqColor(t.liq_score||0)}">${t.liq_score||0}</span>
            </div>
            <div style="font-size:11px;margin-top:4px">${t.liq_label||'—'}</div>
            <div style="font-size:10px;color:var(--accent-orange);margin-top:2px">انزلاق متوقع: ~${t.slip_pct||0}%</div>
          </div>
          <div style="background:var(--bg-card);border-radius:8px;padding:8px 12px;flex:1;min-width:200px">
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">قرب السعر من نطاق الدخول</div>
            <div class="proximity-wrap">
              <div class="proximity-track">
                <div class="proximity-fill" style="width:${t.proximity||0}%;background:${proxColor(t.proximity||0)}"></div>
              </div>
              <span class="proximity-num" style="color:${proxColor(t.proximity||0)}">${t.proximity||0}%</span>
            </div>
            <div style="margin-top:6px">${readyBadgeHtml(t.ready, t.proximity)}</div>
          </div>
        </div>

        <!-- مخطط نطاق الدخول المرئي -->
        <div class="entry-zone-diagram" style="margin-bottom:14px">
          <h3>📍 نطاق الدخول المثالي</h3>
          ${entryZoneDiagram(s.price, t.entry_ideal, t.entry_range_low, t.entry_range_high, t.stop_loss, t.targets?.[0])}
        </div>

        <!-- الأرقام التفصيلية -->
        <div class="trade-grid">
          <div class="trade-box">
            <div class="trade-box-label">الحد الأعلى للدخول</div>
            <div class="trade-box-val" style="color:var(--accent-orange)">${fmt(t.entry_range_high)}</div>
            <div style="font-size:10px;color:var(--text-muted)">لا تدخل فوق هذا السعر</div>
          </div>
          <div class="trade-box" style="border:1px solid rgba(99,179,237,0.3);background:rgba(99,179,237,0.05)">
            <div class="trade-box-label">✨ سعر الدخول المثالي</div>
            <div class="trade-box-val cyan">${fmt(t.entry_ideal)}</div>
            <div style="font-size:10px;color:var(--text-muted)">تقاطع فيبوناتشي + Pivot</div>
          </div>
          <div class="trade-box">
            <div class="trade-box-label">الحد الأدنى للنطاق</div>
            <div class="trade-box-val" style="color:var(--accent-purple)">${fmt(t.entry_range_low)}</div>
            <div style="font-size:10px;color:var(--text-muted)">لو نزل أكثر → راجع السيناريو</div>
          </div>
        </div>

        <div class="trade-grid" style="margin-top:10px">
          <div class="trade-box">
            <div class="trade-box-label">🛑 وقف الخسارة</div>
            <div class="trade-box-val red">${fmt(t.stop_loss)}</div>
            <div style="font-size:10px;color:var(--accent-red)">${t.risk_pct}% مخاطرة من الدخول</div>
          </div>
          <div class="trade-box">
            <div class="trade-box-label">📍 السعر الحالي</div>
            <div class="trade-box-val ${chg>=0?'green':'red'}">${fmt(s.price)}</div>
            <div style="font-size:10px;color:var(--text-muted)">${chg>=0?'+':''}${chg}% اليوم</div>
          </div>
          <div class="trade-box">
            <div class="trade-box-label">🎯 R:R الأول</div>
            <div class="trade-box-val" style="color:${(t.rr_ratios?.[0]||0)>=2?'var(--accent-green)':'var(--accent-yellow)'}">${t.rr_ratios?.[0]||'—'}x</div>
            <div style="font-size:10px;color:var(--text-muted)">${(t.rr_ratios?.[0]||0)>=2?'مقبول ✓':'تحت المعيار ⚠'}</div>
          </div>
        </div>

        <div style="margin-top:12px;margin-bottom:6px;font-size:12px;color:var(--text-secondary)">أهداف جني الأرباح (من سعر الدخول المثالي):</div>

        <!-- الأهداف القريبة (ATR) -->
        <div class="targets-section">
          <div class="targets-section-title">⚡ أهداف قريبة — ATR-based (أيام قليلة)</div>
          <div class="targets-chips">
            ${(t.near_targets||[]).map((tgt, i) => {
              const pct = t.near_pcts?.[i] || 0;
              return `<div class="target-chip-near">
                <div class="tc-label">قريب ${i+1}</div>
                <div class="tc-price green">${fmt(tgt)}</div>
                <div class="tc-pct green">+${pct}%</div>
              </div>`;
            }).join('') || '<span class="muted" style="font-size:11px">ATR غير متاح</span>'}
          </div>
        </div>

        <!-- الأهداف البعيدة (فيبوناتشي) -->
        <div class="targets-section" style="margin-top:10px">
          <div class="targets-section-title">🏆 أهداف بعيدة — فيبوناتشي / Pivot</div>
          <div class="targets-chips">
            ${(t.targets||[]).map((tgt, i) => {
              const rr  = t.rr_ratios?.[i] || 0;
              const pct = t.far_pcts?.[i]  || 0;
              const rrOk = rr >= 2;
              return `<div class="target-chip-far" style="${rrOk?'border-color:rgba(104,211,145,0.35)':''}">
                <div class="tc-label">بعيد ${i+1}</div>
                <div class="tc-price yellow">${fmt(tgt)}</div>
                <div class="tc-pct" style="color:${rrOk?'var(--accent-green)':'var(--accent-yellow)'}">+${pct}% | R:R ${rr}x</div>
              </div>`;
            }).join('')}
          </div>
        </div>

        <!-- وقف الخسارة كنسبة -->
        <div style="margin-top:10px;padding:8px 12px;background:rgba(255,23,68,0.06);border:1px solid rgba(255,23,68,0.2);border-radius:8px;font-size:12px;display:flex;justify-content:space-between;align-items:center">
          <span style="color:var(--text-muted)">🛑 وقف الخسارة</span>
          <span>
            <span class="red" style="font-family:Rajdhani,sans-serif;font-size:15px;font-weight:700">${fmt(t.stop_loss)}</span>
            <span class="red" style="font-size:11px;margin-right:6px">(${t.stop_pct||t.risk_pct ? (t.stop_pct||'-'+t.risk_pct)+'%' : '—'})</span>
          </span>
        </div>
      </div>

      <!-- Fibonacci Levels + Confluence -->
      <div class="info-section" style="grid-column:1/-1">
        <h3>🌀 مستويات فيبوناتشي (52 أسبوع) + التقاطعات</h3>
        ${a.multi_fib?.confluence?.length ? `
        <div style="margin-bottom:12px">
          <div style="font-size:11px;color:var(--accent-yellow);font-weight:600;margin-bottom:8px">
            ⚡ مستويات التقاطع (أقوى المستويات — تلتقي فيها أطر زمنية متعددة)
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
            ${(a.multi_fib.confluence||[]).map(c => {
              const dist = s.price ? Math.abs(c.val - s.price)/s.price*100 : 0;
              const isSupport = c.val < s.price;
              const color = isSupport ? 'var(--accent-green)' : 'var(--accent-red)';
              return `<div style="background:${isSupport?'rgba(104,211,145,0.08)':'rgba(252,129,129,0.08)'};
                border:1px solid ${isSupport?'rgba(104,211,145,0.25)':'rgba(252,129,129,0.25)'};
                border-radius:8px;padding:6px 10px;text-align:center">
                <div style="font-size:10px;color:var(--text-muted)">${c.frames} | ${c.name}</div>
                <div style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700;color:${color}">${c.val}</div>
                <div style="font-size:10px;color:${color}">${isSupport?'دعم':'مقاومة'} ${dist.toFixed(1)}%</div>
                <div style="font-size:9px;color:var(--text-muted)">${'★'.repeat(c.strength)}</div>
              </div>`;
            }).join('')}
          </div>
        </div>` : ''}
        <div class="fib-levels">
          ${renderFibLevels(fib, s.price, s.high52w, s.low52w)}
        </div>
      </div>

      <!-- Pivot Points -->
      <div class="info-section">
        <h3>📌 نقاط المحور الكلاسيكية</h3>
        ${infoRow('R3', fmt(piv.R3), 'red')}
        ${infoRow('R2', fmt(piv.R2), 'orange')}
        ${infoRow('R1', fmt(piv.R1), 'yellow')}
        ${infoRow('PP (المحور)', `<b>${fmt(piv.PP)}</b>`, 'blue')}
        ${infoRow('S1', fmt(piv.S1), 'cyan')}
        ${infoRow('S2', fmt(piv.S2), 'green')}
        ${infoRow('S3', fmt(piv.S3), 'green')}
      </div>

      <!-- MA Analysis -->
      <div class="info-section">
        <h3>📊 تحليل المتوسطات المتحركة</h3>
        ${maCell('SMA20',  s.price, s.sma20)}
        ${maCell('SMA50',  s.price, s.sma50)}
        ${maCell('SMA200', s.price, s.sma200)}
        ${maCell('EMA20',  s.price, s.ema20)}
        ${maCell('EMA50',  s.price, s.ema50)}
        ${infoRow('اتجاه عام', (a.ma_trend||[]).join(' | ') || '—')}
      </div>

      <!-- تأكيد الإشارة -->
      <div class="info-section" style="grid-column:1/-1">
        <h3>✅ تأكيد الإشارة — تقارب المؤشرات</h3>
        ${(() => {
          const c = a.confirmation || {};
          const total = (c.bull_count||0) + (c.bear_count||0);
          return `
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
            <div class="conf-dots">
              ${Array.from({length:Math.max(total,5)},(_,i)=>`
                <div class="conf-dot" style="background:${
                  i < (c.bull_count||0) ? 'var(--accent-green)' :
                  i < total ? 'var(--accent-red)' : 'rgba(255,255,255,0.1)'}"></div>`
              ).join('')}
            </div>
            <div>
              <div style="font-weight:600;font-size:13px">${c.label||'—'}</div>
              <div style="font-size:11px;color:var(--text-muted)">${c.bull_count||0} مؤشر صاعد | ${c.bear_count||0} مؤشر هابط</div>
            </div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            ${(c.signals||[]).map(s=>`<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(104,211,145,0.08);color:var(--accent-green);border:1px solid rgba(104,211,145,0.2)">${s}</span>`).join('')}
          </div>`;
        })()}
      </div>

      <!-- Divergence -->
      ${a.divergences?.length ? `
      <div class="info-section" style="grid-column:1/-1">
        <h3>⚡ تباعد المؤشرات (Divergence)</h3>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${a.divergences.map(d=>`
          <div class="div-badge div-${d.type==='BULLISH'?'bull':'bear'}" style="font-size:12px;padding:8px 12px">
            <span style="font-size:16px">${d.type==='BULLISH'?'🟢':'🔴'}</span>
            <div>
              <div style="font-weight:700">${d.ar}</div>
              <div style="font-size:10px;opacity:0.8;margin-top:2px">قوة الإشارة: ${d.strength}%</div>
            </div>
          </div>`).join('')}
        </div>
      </div>` : ''}

      <!-- Trailing Stops -->
      ${a.trailing_stops?.length ? `
      <div class="info-section" style="grid-column:1/-1">
        <h3>🎯 خطة وقف الخسارة المتحرك (Trailing Stop)</h3>
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:10px">
          حرّك الوقف تلقائياً مع كل هدف تصل إليه لتأمين أرباحك
        </div>
        <div class="trail-timeline">
          ${a.trailing_stops.map(ts=>`
          <div class="trail-step ${ts.level===0?'':''}">
            <div class="trail-num" style="color:${ts.level===0?'var(--accent-red)':ts.level===1?'var(--accent-cyan)':'var(--accent-green)'}">${ts.level}</div>
            <div style="flex:1">
              <div style="font-size:12px">${ts.ar}</div>
              <div style="font-size:10px;color:var(--text-muted);margin-top:2px">${ts.risk}</div>
            </div>
            ${ts.trigger?`<div style="font-size:11px;color:var(--text-muted)">عند: <b style="color:var(--accent-yellow)">${fmt(ts.trigger)}</b></div>`:''}
          </div>`).join('')}
        </div>
      </div>` : ''}

      <!-- Resistance Info -->
      ${a.resistance_info?.near_resistance ? `
      <div class="res-warning" style="grid-column:1/-1">
        <span style="font-size:20px">⚠️</span>
        <div>
          <div style="font-weight:700">${a.resistance_info.warning}</div>
          <div style="font-size:11px;margin-top:4px">
            ${a.resistance_info.nearest.map(r=>`${r.source} ${r.key}: ${r.level} (${r.dist_pct}% بعيد)`).join(' | ')}
          </div>
        </div>
      </div>` : ''}

      <!-- Position Size Calculator -->
      <div class="pos-calc" style="grid-column:1/-1">
        <h3>💰 حاسبة حجم الصفقة المثالي</h3>
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
          <div class="filter-group">
            <span class="filter-label">رأس المال:</span>
            <input id="modalCapital" class="filter-input" type="number" placeholder="50000"
              style="width:120px" oninput="calcModalPosition('${sym}')">
            <span style="font-size:12px;color:var(--text-muted)">ج</span>
          </div>
          <div class="filter-group">
            <span class="filter-label">مخاطرة:</span>
            <select id="modalRisk" class="filter-select" style="width:80px" onchange="calcModalPosition('${sym}')">
              <option value="1">1%</option>
              <option value="2" selected>2%</option>
              <option value="3">3%</option>
            </select>
          </div>
        </div>
        <div id="modalPosResult" style="font-size:12px;color:var(--text-muted)">
          أدخل رأس المال لحساب الكمية المثالية
        </div>
      </div>

      <!-- وقت الدخول الأمثل -->
      ${a.entry_time_hint ? `
      <div style="grid-column:1/-1;padding:10px 14px;background:rgba(99,179,237,0.06);
           border:1px solid rgba(99,179,237,0.2);border-radius:8px;font-size:12px">
        🕐 <b>توقيت الدخول:</b> ${a.entry_time_hint}
      </div>` : ''}

    </div>
  </div>`;

  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('stockModal').style.display = 'flex';
}

function renderFibLevels(fib, price, high, low) {
  if (!fib || !high || !low) return '<div class="muted">بيانات غير متوفرة</div>';
  const range = high - low;
  const levels = [
    { key:'R3',   label:'R3',    color:'#ff1744' },
    { key:'R2',   label:'R2',    color:'#ff5252' },
    { key:'R1',   label:'R1',    color:'#ff8a65' },
    { key:'P',    label:'P',     color:'#b0bec5' },
    { key:'F236', label:'23.6%', color:'#ffeb3b' },
    { key:'F382', label:'38.2%', color:'#f6ad55' },
    { key:'F500', label:'50.0%', color:'#81d4fa' },
    { key:'F618', label:'61.8%', color:'#69f0ae' },
    { key:'F786', label:'78.6%', color:'#00e676' },
  ];
  const min = low  * 0.95;
  const max = high * 1.05;
  const span = max - min;
  return levels.map(l => {
    const val = fib[l.key];
    if (!val) return '';
    const pctPos = Math.max(0, Math.min(100, ((val - min) / span) * 100));
    const pricePct = Math.max(0, Math.min(100, ((price - min) / span) * 100));
    const isActive = Math.abs(val - price) / price < 0.02;
    return `
    <div class="fib-row" style="${isActive?'background:rgba(255,255,255,0.04);border-radius:4px;padding:2px 0':''}">
      <div class="fib-label">${l.label}</div>
      <div class="fib-bar-wrap">
        <div class="fib-bar-fill" style="left:0;width:${pctPos}%;background:${l.color};opacity:0.3"></div>
        <div class="fib-price-line" style="left:${pricePct}%"></div>
      </div>
      <div class="fib-val">${fmt(val)}</div>
    </div>`;
  }).join('');
}

function maCell(label, price, ma) {
  if (!ma) return infoRow(label, '—');
  const diff = price && ma ? ((price - ma) / ma * 100).toFixed(1) : 0;
  const above = price > ma;
  return infoRow(label, `${fmt(ma)} <span class="${above?'green':'red'}" style="font-size:11px">(${above?'+':''}${diff}%)</span>`);
}

function closeModal(e) {
  if (!e || e.target === document.getElementById('stockModal')) {
    document.getElementById('stockModal').style.display = 'none';
  }
}

// ══════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════
function sigBadge(label, color, emoji, size) {
  if (!label) return '';
  const bg  = color || '#888';
  const fz  = size === 'large' ? '14px' : '12px';
  const pad = size === 'large' ? '6px 14px' : '3px 10px';
  return `<span class="sig-badge" style="background:${bg}20;color:${bg};border:1px solid ${bg}40;padding:${pad};font-size:${fz}">
    ${emoji} ${label}
  </span>`;
}

function scoreBar(score) {
  if (score === null || score === undefined) return '—';
  const c = scoreColor(score);
  return `<div class="score-bar">
    <div class="score-track"><div class="score-fill" style="width:${score}%;background:${c}"></div></div>
    <div class="score-num" style="color:${c}">${score}</div>
  </div>`;
}

function scoreColor(s) {
  if (s >= 70) return 'var(--accent-green)';
  if (s >= 55) return 'var(--accent-yellow)';
  if (s >= 40) return 'var(--text-secondary)';
  return 'var(--accent-red)';
}

function rsiCell(rsi) {
  if (!rsi) return '—';
  const c = rsi < 30 ? 'var(--accent-green)' : rsi > 70 ? 'var(--accent-red)' : 'var(--text-primary)';
  const pos = Math.max(0, Math.min(100, rsi));
  return `<div class="rsi-gauge-wrap">
    <div class="rsi-bar"><div class="rsi-pointer" style="left:${pos}%"></div></div>
    <span style="font-family:Rajdhani,sans-serif;font-size:13px;color:${c};font-weight:700">${rsi}</span>
  </div>`;
}

function volCell(vol, avg, cls) {
  if (!vol) return '—';
  return `${fmtVol(vol)}<br><span style="font-size:10px;color:${cls?.includes('↑')||cls?.includes('⚡')||cls?.includes('🔥')?'var(--accent-yellow)':'var(--text-muted)'}">${cls||''}</span>`;
}

function perfCell(v) {
  if (v === null || v === undefined) return '—';
  // TradingView بيرجع Perf.W كنسبة مئوية مباشرة (مثلاً 5.2 = 5.2%)
  const p = parseFloat(v).toFixed(1);
  return `<span class="${v>=0?'green':'red'}">${v>=0?'+':''}${p}%</span>`;
}

function infoRow(key, val, cls) {
  return `<div class="info-row">
    <span class="info-key">${key}</span>
    <span class="info-val ${cls||''}">${val}</span>
  </div>`;
}

function renderPager(id, page, total, cb) {
  if (total <= 1) { document.getElementById(id).innerHTML=''; return; }
  let html = '';
  const start = Math.max(1, page-2);
  const end   = Math.min(total, page+2);
  if (page > 1) html += `<button class="page-btn" onclick="(${cb.toString()})(${page-1})">‹</button>`;
  if (start > 1) html += `<button class="page-btn" onclick="(${cb.toString()})(1)">1</button>${start>2?'<span class="muted">...</span>':''}`;
  for (let p=start; p<=end; p++)
    html += `<button class="page-btn ${p===page?'active':''}" onclick="(${cb.toString()})(${p})">${p}</button>`;
  if (end < total) html += `${end<total-1?'<span class="muted">...</span>':''}<button class="page-btn" onclick="(${cb.toString()})(${total})">${total}</button>`;
  if (page < total) html += `<button class="page-btn" onclick="(${cb.toString()})(${page+1})">›</button>`;
  document.getElementById(id).innerHTML = html;
}

function fmt(n) {
  if (n === null || n === undefined) return '—';
  const f = parseFloat(n);
  if (isNaN(f)) return '—';
  return f.toFixed(f < 10 ? 3 : f < 100 ? 2 : 1);
}
function fmtVol(n) {
  if (!n) return '—';
  if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(0) + 'K';
  return n.toFixed(0);
}
function fmtCap(n) {
  if (!n) return '—';
  if (n >= 1e12) return (n/1e12).toFixed(2) + ' تريليون ج';
  if (n >= 1e9)  return (n/1e9).toFixed(1)  + ' مليار ج';
  if (n >= 1e6)  return (n/1e6).toFixed(1)  + ' مليون ج';
  return n.toFixed(0) + ' ج';
}
function pct(a, b) { return b ? Math.round(a/b*100) : 0; }
function avg(arr)  { return arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0; }

function qualColor(tq) {
  if (!tq) return 'var(--text-muted)';
  if (tq >= 80) return '#00e676';
  if (tq >= 60) return '#f6e05e';
  if (tq >= 40) return '#63b3ed';
  return '#94a3b8';
}
function liqColor(liq) {
  if (liq >= 80) return '#4fd1c5';
  if (liq >= 60) return '#68d391';
  if (liq >= 40) return '#f6e05e';
  if (liq >= 20) return '#f6ad55';
  return '#fc8181';
}
function proxColor(p) {
  if (p >= 100) return '#00e676';
  if (p >= 70)  return '#f6e05e';
  if (p >= 40)  return '#63b3ed';
  return '#94a3b8';
}
function readyBadgeHtml(ready, prox, scenario) {
  if (scenario === "MARKET" || ready)
    return `<span class="ready-badge ready">✅ ادخل بسعر السوق الآن</span>`;
  if (scenario === "NEAR" || (prox||0) >= 70)
    return `<span class="ready-badge near">🎯 قريب من نطاق الدخول</span>`;
  return `<span class="ready-badge waiting">⏳ استنى — السعر بعيد عن الدخول</span>`;
}

function entryZoneDiagram(price, ideal, low, high, stop, target1) {
  // رسم مخطط نطاق الدخول على شريط أفقي
  const vals = [stop, low, ideal, high, price, target1].filter(v => v !== null && v !== undefined);
  if (vals.length < 3) return '<div class="muted" style="padding:8px">بيانات غير كافية</div>';
  const mn = Math.min(...vals) * 0.998;
  const mx = Math.max(...vals) * 1.002;
  const span = mx - mn;
  const toP = v => Math.max(0, Math.min(100, ((v - mn) / span) * 100));

  const zoneLeft  = toP(Math.min(low, high));
  const zoneRight = toP(Math.max(low, high));
  const zoneW     = zoneRight - zoneLeft;

  const markers = [
    { v: stop,    color:'#fc8181', label:'وقف', above:true  },
    { v: low,     color:'#b794f4', label:'أدنى النطاق', above:false },
    { v: ideal,   color:'#63b3ed', label:'مثالي ✨', above:true  },
    { v: high,    color:'#f6ad55', label:'أقصى الدخول', above:false },
    { v: price,   color:'#f6e05e', label:`الآن`, above:true, thick:true },
    { v: target1, color:'#68d391', label:'الهدف 1', above:false },
  ].filter(m => m.v !== null && m.v !== undefined);

  const linesHtml = markers.map(m => {
    const p = toP(m.v);
    return `
      <div class="ez-line" style="left:${p}%;background:${m.color};width:${m.thick?3:2}px;opacity:${m.thick?1:0.8}"></div>
      <div class="ez-marker" style="left:${p}%;color:${m.color};${m.above?'top:-20px':'top:auto;bottom:-20px'}">${fmt(m.v)}</div>
      <div class="ez-label" style="left:${p}%;${!m.above?'bottom:-18px':'top:-32px'}">${m.label}</div>
    `;
  }).join('');

  return `<div class="entry-zone-track">
    <div class="ez-fill" style="left:${zoneLeft}%;width:${zoneW}%"></div>
    ${linesHtml}
  </div>
  <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:4px;padding:0 8px">
    <span>${fmt(mn)}</span>
    <span style="color:var(--accent-blue)">◀ نطاق الدخول ▶</span>
    <span>${fmt(mx)}</span>
  </div>`;
}

// ══════════════════════════════════════════════════════
// ALERT SYSTEM — صوتي + مرئي (مع حفظ localStorage)
// ══════════════════════════════════════════════════════

let alertPanelOpen = false;
let alertPollTimer = null;
const ALERT_POLL   = 30_000;
const TOAST_TTL    = 8_000;

// ── تحميل الحالة المحفوظة ──
let alertHistory = JSON.parse(localStorage.getItem('egx_alert_history') || '[]');
let panelItems   = JSON.parse(localStorage.getItem('egx_panel_items')   || '[]');
panelItems = panelItems.map(p => ({ ...p, time: new Date(p.time) }));

function saveAlertState() {
  localStorage.setItem('egx_alert_history', JSON.stringify(alertHistory.slice(-500)));
  const toSave = panelItems.slice(0, 50).map(p => ({ ...p, time: (p.time instanceof Date ? p.time : new Date(p.time)).toISOString() }));
  localStorage.setItem('egx_panel_items', JSON.stringify(toSave));
}

// ── Web Audio: توليد نغمات بدون ملفات صوتية ──
let audioCtx = null;
function getAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function playTone(type) {
  try {
    const ctx = getAudio();
    const gain = ctx.createGain();
    gain.connect(ctx.destination);

    const configs = {
      // دخول: نغمة صاعدة مبهجة (ثلاث نبضات)
      entry: [
        { f:523, t:0,    d:0.15, g:0.4  },
        { f:659, t:0.15, d:0.15, g:0.4  },
        { f:784, t:0.30, d:0.25, g:0.5  },
      ],
      // وقف خسارة: نغمة هابطة تحذيرية
      stop: [
        { f:440, t:0,    d:0.2,  g:0.5  },
        { f:330, t:0.2,  d:0.2,  g:0.5  },
        { f:220, t:0.4,  d:0.35, g:0.6  },
      ],
      // هدف قريب: نبضة واحدة قصيرة إيجابية
      target: [
        { f:880, t:0,    d:0.1,  g:0.35 },
        { f:1046,t:0.12, d:0.2,  g:0.4  },
      ],
      // هدف بعيد: نغمة احتفالية
      target_far: [
        { f:523, t:0,    d:0.1,  g:0.35 },
        { f:659, t:0.1,  d:0.1,  g:0.35 },
        { f:784, t:0.2,  d:0.1,  g:0.35 },
        { f:1047,t:0.3,  d:0.3,  g:0.5  },
      ],
    };

    const notes = configs[type] || configs.target;
    const now   = ctx.currentTime;

    notes.forEach(({ f, t, d, g }) => {
      const osc  = ctx.createOscillator();
      const gNode = ctx.createGain();
      osc.connect(gNode);
      gNode.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(f, now + t);
      gNode.gain.setValueAtTime(0, now + t);
      gNode.gain.linearRampToValueAtTime(g, now + t + 0.02);
      gNode.gain.exponentialRampToValueAtTime(0.001, now + t + d);
      osc.start(now + t);
      osc.stop(now + t + d + 0.05);
    });
  } catch(e) { /* المتصفح مش بيسمح بالصوت قبل تفاعل المستخدم */ }
}

// ── Toast مرئي ──
function showToast(sym, label, price, change, color, sound, sourceTag, quality) {
  playTone(sound);
  const id  = `toast_${Date.now()}_${Math.random().toString(36).slice(2,6)}`;
  const chg = change != null ? `${change >= 0 ? '+' : ''}${change}%` : '';
  const tag = sourceTag
    ? `<span style="font-size:10px;background:${color}22;color:${color};padding:1px 6px;border-radius:10px;border:1px solid ${color}44">${sourceTag}</span>`
    : '';
  const qColor = quality >= 80 ? '#00e676' : quality >= 60 ? '#f6e05e' : '#63b3ed';
  const qBadge = quality != null
    ? `<span style="font-family:Rajdhani,sans-serif;font-size:13px;font-weight:700;color:${qColor};background:${qColor}18;border:1px solid ${qColor}44;border-radius:8px;padding:1px 7px" title="جودة الصفقة">${Math.round(quality)}</span>`
    : '';
  const toast = document.createElement('div');
  toast.className = 'alert-toast';
  toast.id        = id;
  toast.style.borderColor = color;
  toast.innerHTML = `
    <div class="toast-header">
      <span class="toast-sym" style="color:${color};font-size:20px">${sym}</span>
      ${qBadge}
      ${tag}
      <button class="toast-close" onclick="event.stopPropagation();dismissToast('${id}')">✕</button>
    </div>
    <div style="color:${color};font-size:13px;font-weight:700;margin:4px 0">${label}</div>
    <div style="font-size:12px;color:var(--text-secondary)">
      السعر الحالي:
      <span style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700;color:var(--text-primary)">${fmt(price)} ج</span>
      <span style="color:${(change||0)>=0?'var(--accent-green)':'var(--accent-red)'}"> ${chg}</span>
    </div>
    <div class="toast-bar" style="background:${color};animation-duration:${TOAST_TTL}ms"></div>
  `;
  toast.onclick = () => { openModal(sym); dismissToast(id); };
  document.getElementById('toastContainer').prepend(toast);
  setTimeout(() => dismissToast(id), TOAST_TTL);
}

function dismissToast(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('fadeout');
  setTimeout(() => el.remove(), 350);
}

// ── Deduplication: لا نكرر نفس التنبيه في نفس اليوم ──
function alertKey(sym, type) {
  const today = new Date().toDateString();
  return `${today}|${sym}|${type}`;
}
function wasAlerted(sym, type) {
  return alertHistory.includes(alertKey(sym, type));
}
function markAlerted(sym, type) {
  const k = alertKey(sym, type);
  if (!alertHistory.includes(k)) alertHistory.push(k);
  // احتفظ بآخر 500 مدخل فقط
  if (alertHistory.length > 500) alertHistory = alertHistory.slice(-500);
}

// ── فحص التنبيهات ──
async function checkAlerts() {
  // ── بناء قائمة الأسهم المراقبة ──
  // 1. أسهم المتابعة اليدوية (watchlist)
  // 2. أسهم أفضل الفرص تلقائياً (TOP_DATA)
  const topSyms     = TOP_DATA.map(t => t.symbol);
  const allSyms     = [...new Set([...watchlist, ...topSyms])];
  if (!allSyms.length) return;

  try {
    const r = await fetch(`/api/alerts/check?w=${allSyms.join(',')}`);
    const j = await r.json();
    if (!j.ok || !j.alerts.length) return;

    let newCount = 0;
    j.alerts.forEach(a => {
      // هل السهم من أفضل الفرص أم من المتابعة اليدوية؟
      const isTop      = topSyms.includes(a.symbol);
      const isWatchlist = watchlist.includes(a.symbol);
      const sourceTag  = isWatchlist ? '⭐ متابعة' : '🎯 فرصة';

      a.triggered.forEach(trig => {
        if (wasAlerted(a.symbol, trig.type)) return;
        markAlerted(a.symbol, trig.type);

        // ── بناء رسالة التنبيه التفصيلية ──
        const topData  = TOP_DATA.find(t => t.symbol === a.symbol);
        let extraLabel = trig.label;

        if (trig.type === 'ENTRY' && topData) {
          extraLabel = `✅ وصل نطاق الدخول — ${fmt(topData.entry)} ج`;
        } else if (trig.type?.startsWith('NEAR_T') && topData) {
          const idx  = parseInt(trig.type.replace('NEAR_T','')) - 1;
          const pct  = topData.near_pcts?.[idx];
          const tgtP = topData.near_targets?.[idx];
          extraLabel = `🎯 الهدف القريب ${idx+1} — ${fmt(tgtP)} ج (+${pct}%)`;
        } else if (trig.type?.startsWith('FAR_T') && topData) {
          const idx  = parseInt(trig.type.replace('FAR_T','')) - 1;
          const pct  = topData.far_pcts?.[idx];
          const tgtP = topData.targets?.[idx];
          extraLabel = `🏆 الهدف البعيد ${idx+1} — ${fmt(tgtP)} ج (+${pct}%)`;
        } else if (trig.type === 'STOP' && topData) {
          extraLabel = `🛑 وصل وقف الخسارة — ${fmt(topData.stop)} ج (${topData.risk_pct}%-)`;
        }

        const quality    = topData?.trade_quality ?? null;

        showToast(a.symbol, extraLabel, a.price, a.change, trig.color, trig.sound, sourceTag, quality);
        addToAlertPanel(a, { ...trig, label: extraLabel, sourceTag, quality });
        newCount++;
      });
    });

    if (newCount > 0) {
      document.getElementById('alertBtn').classList.add('has-alerts');
    }
  } catch(e) {}
}

// ── إضافة للـ Panel ──
function addToAlertPanel(stock, trig) {
  panelItems.unshift({ stock, trig, time: new Date() });
  if (panelItems.length > 50) panelItems = panelItems.slice(0, 50);
  saveAlertState();
  renderAlertPanel();
}

function renderAlertPanel() {
  const count = panelItems.length;
  document.getElementById('alertPanelCount').textContent = count ? `${count} تنبيه` : '';

  if (!count) {
    const watchInfo = watchlist.length
      ? `<button onclick="testAlert()" style="margin-top:14px;background:rgba(99,179,237,0.12);border:1px solid var(--border-bright);color:var(--accent-blue);padding:6px 16px;border-radius:8px;cursor:pointer;font-family:Cairo,sans-serif;font-size:12px">🧪 اختبار الصوت والتنبيه</button>`
      : `<div style="margin-top:12px;background:rgba(246,224,94,0.08);border:1px solid rgba(246,224,94,0.2);border-radius:8px;padding:8px 12px;font-size:11px;color:var(--accent-yellow)">⭐ أضف أسهم للمتابعة أولاً من الجدول الرئيسي</div>`;
    document.getElementById('alertPanelBody').innerHTML = `
      <div style="padding:30px;text-align:center;color:var(--text-muted)">
        <div style="font-size:36px;margin-bottom:10px">🔔</div>
        <div style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:6px">لا توجد تنبيهات حتى الآن</div>
        <div style="font-size:11px;line-height:1.8">
          التنبيهات تصل كل 30 ثانية تلقائياً<br>
          عند وصول السعر لنطاق الدخول أو الأهداف أو وقف الخسارة<br>
          والسجل محفوظ حتى بعد إغلاق التطبيق
        </div>
        ${watchInfo}
      </div>`;
    return;
  }

  document.getElementById('alertPanelBody').innerHTML =
    `<div style="padding:8px 16px 6px;background:rgba(255,255,255,0.02);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:11px;color:var(--text-muted)">محفوظ تلقائياً — ${count} تنبيه</span>
      <button onclick="testAlert()" style="background:none;border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:3px 10px;font-size:10px;cursor:pointer;font-family:Cairo,sans-serif">🧪 اختبار</button>
    </div>` +
    panelItems.map((item, idx) => {
    const { stock, trig, time } = item;
    const t2 = time instanceof Date ? time : new Date(time);
    const timeStr = t2.toLocaleString('ar-EG', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
    return `
    <div class="alert-item" onclick="openModal('${stock.symbol}'); toggleAlertPanel()">
      <div style="width:8px;height:8px;border-radius:50%;background:${trig.color};flex-shrink:0;margin-top:4px;box-shadow:0 0 6px ${trig.color}66"></div>
      <div class="alert-item-sym">${stock.symbol}</div>
      ${trig.quality != null ? `<span style="font-family:Rajdhani,sans-serif;font-size:12px;font-weight:700;color:${trig.quality>=80?'#00e676':trig.quality>=60?'#f6e05e':'#63b3ed'};background:rgba(255,255,255,0.05);border-radius:6px;padding:1px 6px;flex-shrink:0">${Math.round(trig.quality)}</span>` : ''}
      <div class="alert-item-info">
        <div class="alert-item-label" style="color:${trig.color}">${trig.label}</div>
        <div class="alert-item-price">
          السعر: <b>${fmt(trig.price)}</b> ج &nbsp;|&nbsp; ${timeStr}
          ${trig.sourceTag ? `&nbsp;|&nbsp;<span style="color:var(--text-muted);font-size:10px">${trig.sourceTag}</span>` : ''}
        </div>
      </div>
      <button class="alert-item-dismiss" onclick="event.stopPropagation();dismissPanelItem(${idx})">✕</button>
    </div>`;
  }).join('');
}

function dismissPanelItem(idx) {
  panelItems.splice(idx, 1);
  if (!panelItems.length) document.getElementById('alertBtn').classList.remove('has-alerts');
  renderAlertPanel();
}

// ══════════════════════════════════════════════════════
// Security Info & Password Setup (Phase 1 Improvements)
// ══════════════════════════════════════════════════════
function showSecurityInfo() {
  const modal = document.getElementById('securityModal');
  if (modal) { modal.style.display = 'flex'; return; }
  const div = document.createElement('div');
  div.id = 'securityModal';
  div.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center';
  div.onclick = e => { if(e.target===div) div.style.display='none'; };
  div.innerHTML = `
    <div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:16px;padding:28px;max-width:420px;width:90%;direction:rtl">
      <h3 style="margin:0 0 16px;font-size:18px;display:flex;align-items:center;gap:8px">🔒 معلومات الأمان</h3>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="background:var(--bg-card);border-radius:10px;padding:14px;border:1px solid var(--border)">
          <div style="font-size:12px;color:var(--accent-green);font-weight:700;margin-bottom:6px">🔒 تشفير البيانات</div>
          <div style="font-size:12px;color:var(--text-secondary);line-height:1.8">
            • تشفير AES-128-CBC عبر Fernet<br>
            • اشتقاق مفاتيح PBKDF2-HMAC-SHA256<br>
            • ملح تشفير فريد لكل تثبيت<br>
            • البيانات الحساسة مشفرة على القرص
          </div>
        </div>
        <div style="background:var(--bg-card);border-radius:10px;padding:14px;border:1px solid var(--border)">
          <div style="font-size:12px;color:var(--accent-blue);font-weight:700;margin-bottom:6px">🔐 المصادقة JWT</div>
          <div style="font-size:12px;color:var(--text-secondary);line-height:1.8">
            • رموز JWT مع توقيع HMAC-SHA256<br>
            • صلاحية محدودة بالوقت (24 ساعة)<br>
            • وضع المستخدم الواحد بدون كلمة مرور<br>
            • 🔑 أضف كلمة مرور لحماية التطبيق
          </div>
        </div>
        <div style="background:var(--bg-card);border-radius:10px;padding:14px;border:1px solid var(--border)">
          <div style="font-size:12px;color:var(--accent-purple);font-weight:700;margin-bottom:6px">🛡️ اتصال آمن</div>
          <div style="font-size:12px;color:var(--text-secondary);line-height:1.8">
            • SSL/TLS لجميع طلبات API الخارجية<br>
            • التحقق من شهادات الخادم<br>
            • حماية من هجمات MITM
          </div>
        </div>
        <div style="background:rgba(252,129,129,0.06);border-radius:10px;padding:14px;border:1px solid rgba(252,129,129,0.2)">
          <div style="font-size:12px;color:var(--accent-red);font-weight:700;margin-bottom:6px">⚠️ تنويه المخاطر</div>
          <div style="font-size:12px;color:var(--text-secondary);line-height:1.8">
            هذا التطبيق للأغراض التعليمية والبحثية فقط ولا يعتبر استشارة مالية.
            قرارات التداول الآلية تحمل مخاطر مالية كبيرة وقد تؤدي إلى خسارة رأس المال.
            المستخدم يتحمل المسؤولية الكاملة عن قراراته الاستثمارية.
            لا تداول بأموال لا تتحمل خسارتها.
          </div>
        </div>
      </div>
      <button onclick="document.getElementById('securityModal').style.display='none'"
        style="width:100%;margin-top:16px;background:var(--bg-secondary);border:1px solid var(--border);
               color:var(--text-primary);padding:10px;border-radius:10px;cursor:pointer;
               font-family:Cairo,sans-serif;font-size:14px">
        إغلاق
      </button>
    </div>`;
  document.body.appendChild(div);
}

function showPasswordModal() {
  const modal = document.getElementById('passwordModal');
  if (modal) { modal.style.display = 'flex'; return; }
  const div = document.createElement('div');
  div.id = 'passwordModal';
  div.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center';
  div.onclick = e => { if(e.target===div) div.style.display='none'; };
  div.innerHTML = `
    <div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:16px;padding:28px;max-width:380px;width:90%;direction:rtl">
      <h3 style="margin:0 0 16px;font-size:18px;display:flex;align-items:center;gap:8px">🔑 إعداد كلمة المرور</h3>
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:16px;line-height:1.8">
        حماية التطبيق بكلمة مرور تفعّل نظام المصادقة JWT.<br>
        عند تعيين كلمة مرور، سيتطلب التطبيق تسجيل الدخول عند كل فتح.
      </div>
      <div style="display:flex;flex-direction:column;gap:10px">
        <input id="pwdCurrent" type="password" placeholder="كلمة المرور الحالية (إن وجدت)"
          style="background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);
                 padding:10px 14px;border-radius:8px;font-family:Cairo,sans-serif;font-size:14px;outline:none">
        <input id="pwdNew" type="password" placeholder="كلمة المرور الجديدة"
          style="background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);
                 padding:10px 14px;border-radius:8px;font-family:Cairo,sans-serif;font-size:14px;outline:none">
        <input id="pwdConfirm" type="password" placeholder="تأكيد كلمة المرور"
          style="background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);
                 padding:10px 14px;border-radius:8px;font-family:Cairo,sans-serif;font-size:14px;outline:none">
      </div>
      <div id="pwdMsg" style="font-size:12px;margin-top:10px;min-height:18px"></div>
      <div style="display:flex;gap:10px;margin-top:16px">
        <button onclick="setPassword()" style="flex:1;background:rgba(104,211,145,0.15);border:1px solid rgba(104,211,145,0.4);
               color:var(--accent-green);padding:10px;border-radius:10px;cursor:pointer;font-family:Cairo,sans-serif;font-size:14px;font-weight:700">
          حفظ
        </button>
        <button onclick="removePassword()" style="flex:1;background:rgba(252,129,129,0.1);border:1px solid rgba(252,129,129,0.3);
               color:var(--accent-red);padding:10px;border-radius:10px;cursor:pointer;font-family:Cairo,sans-serif;font-size:14px">
          إزالة
        </button>
      </div>
      <button onclick="document.getElementById('passwordModal').style.display='none'"
        style="width:100%;margin-top:10px;background:var(--bg-secondary);border:1px solid var(--border);
               color:var(--text-primary);padding:10px;border-radius:10px;cursor:pointer;font-family:Cairo,sans-serif;font-size:14px">
        إغلاق
      </button>
    </div>`;
  document.body.appendChild(div);
}

async function setPassword() {
  const current = document.getElementById('pwdCurrent')?.value || '';
  const newPwd = document.getElementById('pwdNew')?.value || '';
  const confirm = document.getElementById('pwdConfirm')?.value || '';
  const msg = document.getElementById('pwdMsg');
  if (!newPwd) { msg.style.color='var(--accent-red)'; msg.textContent='أدخل كلمة المرور الجديدة'; return; }
  if (newPwd.length < 4) { msg.style.color='var(--accent-red)'; msg.textContent='كلمة المرور قصيرة جداً (4 أحرف على الأقل)'; return; }
  if (newPwd !== confirm) { msg.style.color='var(--accent-red)'; msg.textContent='كلمتا المرور غير متطابقتين'; return; }
  try {
    const r = await fetch('/api/auth/set-password', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({current_password: current, new_password: newPwd})
    });
    const j = await r.json();
    if (j.ok) {
      msg.style.color='var(--accent-green)'; msg.textContent='✅ تم تعيين كلمة المرور بنجاح';
      document.getElementById('btnPassword').querySelector('span').textContent = '🔐';
      updateSecurityBadge(true);
    } else {
      msg.style.color='var(--accent-red)'; msg.textContent=j.detail || 'خطأ في تعيين كلمة المرور';
    }
  } catch(e) {
    msg.style.color='var(--accent-red)'; msg.textContent='خطأ: ' + e.message;
  }
}

async function removePassword() {
  const current = document.getElementById('pwdCurrent')?.value || '';
  const msg = document.getElementById('pwdMsg');
  try {
    const r = await fetch('/api/auth/set-password', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({current_password: current, new_password: ''})
    });
    const j = await r.json();
    if (j.ok) {
      msg.style.color='var(--accent-green)'; msg.textContent='✅ تم إزالة كلمة المرور';
      document.getElementById('btnPassword').querySelector('span').textContent = '🔑';
      updateSecurityBadge(false);
    } else {
      msg.style.color='var(--accent-red)'; msg.textContent=j.detail || 'خطأ في إزالة كلمة المرور';
    }
  } catch(e) {
    msg.style.color='var(--accent-red)'; msg.textContent='خطأ: ' + e.message;
  }
}

function updateSecurityBadge(hasPassword) {
  const badge = document.getElementById('securityBadge');
  if (!badge) return;
  if (hasPassword) {
    badge.innerHTML = '<span style="font-size:14px">🔐</span><span style="font-size:11px;color:var(--accent-green)">محمي</span>';
    badge.style.borderColor = 'rgba(104,211,145,0.3)';
  } else {
    badge.innerHTML = '<span style="font-size:14px">🔒</span><span style="font-size:11px;color:var(--accent-cyan)">مشفّر</span>';
    badge.style.borderColor = 'rgba(104,211,145,0.2)';
  }
}

// Check password status on load
async function checkSecurityStatus() {
  try {
    const r = await fetchWithTimeout('/api/settings', 3000);
    const j = await r.json();
    if (j.ok && j.settings) {
      updateSecurityBadge(!!j.settings.password_hash);
      if (j.settings.password_hash) {
        const btn = document.getElementById('btnPassword');
        if (btn) btn.querySelector('span').textContent = '🔐';
      }
    }
  } catch(e) {}
}

function clearAllAlerts() {
  panelItems = [];
  alertHistory = [];
  saveAlertState();
  document.getElementById('alertBtn').classList.remove('has-alerts');
  renderAlertPanel();
}

function toggleAlertPanel() {
  alertPanelOpen = !alertPanelOpen;
  const panel = document.getElementById('alertPanel');
  panel.style.display = alertPanelOpen ? 'block' : 'none';
  if (alertPanelOpen) {
    document.getElementById('alertBtn').classList.remove('has-alerts');
    renderAlertPanel();
  }
}

// ── بدء الـ Polling ──
function startAlertPolling() {
  if (alertPollTimer) clearInterval(alertPollTimer);
  setTimeout(checkAlerts, 3000); // بعد تحميل البيانات
  alertPollTimer = setInterval(checkAlerts, ALERT_POLL);
}

// ── اختبار التنبيهات ──
function testAlert() {
  const sym = TOP_DATA[0]?.symbol || watchlist[0] || 'COMI';
  const tq  = TOP_DATA[0]?.trade_quality || 87;
  const demos = [
    { label:`✅ وصل نطاق الدخول — ${fmt(TOP_DATA[0]?.entry||24.50)} ج`,
      color:'#00e676', sound:'entry',      price:TOP_DATA[0]?.entry||24.50,  change: 2.3,  type:'ENTRY'  },
    { label:`🎯 الهدف القريب 1 — ${fmt(TOP_DATA[0]?.near_targets?.[0]||25.48)} ج (+${TOP_DATA[0]?.near_pcts?.[0]||3.9}%)`,
      color:'#69f0ae', sound:'target',     price:TOP_DATA[0]?.near_targets?.[0]||25.48, change: 4.0, type:'NEAR_T1' },
    { label:`🏆 الهدف البعيد 1 — ${fmt(TOP_DATA[0]?.targets?.[0]||39.00)} ج (+${TOP_DATA[0]?.far_pcts?.[0]||59}%)`,
      color:'#f6e05e', sound:'target_far', price:TOP_DATA[0]?.targets?.[0]||39.00,  change:12.0,  type:'FAR_T1'  },
    { label:`🛑 وصل وقف الخسارة — ${fmt(TOP_DATA[0]?.stop||18.27)} ج`,
      color:'#ff1744', sound:'stop',       price:TOP_DATA[0]?.stop||18.27,   change:-5.2,  type:'STOP'   },
  ];
  demos.forEach((d, i) => {
    setTimeout(() => {
      showToast(sym, d.label, d.price, d.change, d.color, d.sound, '🎯 فرصة', tq);
      addToAlertPanel(
        { symbol: sym, price: d.price, change: d.change },
        { label: d.label, color: d.color, price: d.price,
          type: 'TEST_' + d.type, sourceTag: '🧪 تجريبي', quality: tq }
      );
    }, i * 950);
  });
}

// إغلاق الـ panel لما تضغط خارجه
document.addEventListener('click', e => {
  const panel = document.getElementById('alertPanel');
  const btn   = document.getElementById('alertBtn');
  if (alertPanelOpen && panel && !panel.contains(e.target) && !btn.contains(e.target)) {
    alertPanelOpen = false;
    panel.style.display = 'none';
  }
});

// استعادة الـ dot لو في تنبيهات محفوظة من جلسة سابقة
if (panelItems.length > 0) {
  setTimeout(() => document.getElementById('alertBtn')?.classList.add('has-alerts'), 600);
}


// ══════════════════════════════════════════════════════
// switchTab — نضيف market و trades
// ══════════════════════════════════════════════════════
// switchTab is defined below (full version with all tabs including autopilot)

// ══════════════════════════════════════════════════════
// Market Overview
// ══════════════════════════════════════════════════════
let _marketData = null;

async function fetchMarket() {
  try {
    const r = await fetchWithTimeout('/api/market', 10000);
    const j = await r.json();
    if (j.ok) _marketData = j;
  } catch(e) {}
}

async function renderMarket() {
  if (!_marketData) await fetchMarket();
  if (!_breadthData) await fetchBreadth();
  renderBreadthBar();
  const m = _marketData;
  if (!m) {
    document.getElementById('marketKPIs').innerHTML =
      '<div class="empty-state"><div class="empty-icon">📡</div><p>جاري تحميل بيانات السوق...</p></div>';
    return;
  }

  // Banner حالة السوق
  const isOpen  = m.is_open;
  const banner  = `<div class="market-banner ${isOpen?'open':'closed'}" style="grid-column:1/-1">
    <span style="font-size:24px">${isOpen?'🟢':'🔴'}</span>
    <div>
      <div style="font-weight:700;font-size:14px">${m.market_status}</div>
      <div style="font-size:11px;color:var(--text-muted)">البورصة المصرية — EGX</div>
    </div>
    ${m.egx30_price ? `
    <div style="margin-right:auto;text-align:left">
      <div style="font-size:11px;color:var(--text-muted)">EGX30</div>
      <div style="font-family:Rajdhani,sans-serif;font-size:20px;font-weight:700">
        ${fmt(m.egx30_price)}
        <span class="${(m.egx30_chg||0)>=0?'green':'red'}" style="font-size:13px">
          ${(m.egx30_chg||0)>=0?'+':''}${(m.egx30_chg||0).toFixed(2)}%
        </span>
      </div>
    </div>` : ''}
  </div>`;

  // KPIs
  const kpis = [
    { label:'إجمالي الأسهم',  value: m.total_stocks,  color:'var(--accent-blue)'  },
    { label:'أسهم صاعدة',     value: m.advancing,     color:'var(--accent-green)' },
    { label:'أسهم هابطة',     value: m.declining,     color:'var(--accent-red)'   },
    { label:'محايدة',         value: m.total_stocks - m.advancing - m.declining,
                                                       color:'var(--text-muted)'   },
  ];
  document.getElementById('marketKPIs').innerHTML = banner +
    kpis.map(k => `<div class="kpi-card">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value" style="color:${k.color}">${k.value}</div>
    </div>`).join('');

  // Top gainers
  document.getElementById('topGainers').innerHTML =
    (m.top_gainers||[]).map(s => `
    <div class="mover-row" onclick="openModal('${s.sym}')">
      <div class="mover-sym">${s.sym}</div>
      <div class="mover-chg green">+${(s.chg||0).toFixed(2)}%</div>
      <div style="flex:1;font-size:11px;color:var(--text-muted)">${s.sector||''}</div>
      ${s.vs_egx30!=null ? `<div class="mover-vs ${s.vs_egx30>=0?'green':'red'}">${s.vs_egx30>=0?'+':''}${s.vs_egx30}% vs EGX30</div>` : ''}
    </div>`).join('') || '<div class="muted" style="padding:12px;font-size:12px">لا بيانات</div>';

  // Top losers
  document.getElementById('topLosers').innerHTML =
    (m.top_losers||[]).map(s => `
    <div class="mover-row" onclick="openModal('${s.sym}')">
      <div class="mover-sym">${s.sym}</div>
      <div class="mover-chg red">${(s.chg||0).toFixed(2)}%</div>
      <div style="flex:1;font-size:11px;color:var(--text-muted)">${s.sector||''}</div>
      ${s.vs_egx30!=null ? `<div class="mover-vs ${s.vs_egx30>=0?'green':'red'}">${s.vs_egx30>=0?'+':''}${s.vs_egx30}% vs EGX30</div>` : ''}
    </div>`).join('') || '<div class="muted" style="padding:12px;font-size:12px">لا بيانات</div>';

  // Sector Heatmap
  const sp = m.sector_perf || {};
  const maxAbs = Math.max(...Object.values(sp).map(Math.abs), 1);
  document.getElementById('sectorHeatmap').innerHTML = `<div class="heatmap-grid">` +
    Object.entries(sp).sort((a,b)=>b[1]-a[1]).map(([sec, chg]) => {
      const intensity = Math.min(1, Math.abs(chg) / maxAbs);
      const isPos = chg >= 0;
      const bg = isPos
        ? `rgba(0,230,118,${0.1 + intensity*0.5})`
        : `rgba(255,23,68,${0.1 + intensity*0.5})`;
      return `<div class="heatmap-cell" style="background:${bg}" onclick="filterBySector('${sec}')">
        <div class="hm-sector">${sec}</div>
        <div class="hm-chg" style="color:${isPos?'#00e676':'#ff1744'}">${isPos?'+':''}${chg}%</div>
      </div>`;
    }).join('') + `</div>`;
}

function filterBySector(sec) {
  switchTab('overview');
  document.getElementById('overSector').value = sec;
  renderOverview();
}


// ══════════════════════════════════════════════════════
// Trades System
// ══════════════════════════════════════════════════════
let _trades = [];

async function loadTradesData() {
  try {
    const r = await fetchWithTimeout('/api/trades', 8000);
    const j = await r.json();
    if (j.ok) {
      _trades = j.trades || [];
      document.getElementById('badgeTrades').textContent =
        _trades.filter(t => t.status === 'OPEN').length;
    }
  } catch(e) {}
}

function renderTrades() {
  loadTradesData().then(() => {
    const open   = _trades.filter(t => t.status === 'OPEN');
    const closed = _trades.filter(t => t.status === 'CLOSED');
    const totalPnl = closed.reduce((s,t) => s + (t.pnl_egp||0), 0);
    const wins     = closed.filter(t => (t.pnl_egp||0) > 0).length;
    const winRate  = closed.length ? Math.round(wins/closed.length*100) : 0;

    // KPIs
    document.getElementById('tradesKPIs').innerHTML = [
      { label:'صفقات مفتوحة',   value: open.length,        color:'var(--accent-cyan)'  },
      { label:'صفقات مغلقة',   value: closed.length,       color:'var(--text-muted)'   },
      { label:'إجمالي الربح/خسارة', value: `${totalPnl>=0?'+':''}${totalPnl.toFixed(0)} ج`,
        color: totalPnl>=0?'var(--accent-green)':'var(--accent-red)' },
      { label:'نسبة الفوز',    value: `${winRate}%`,       color:'var(--accent-yellow)'},
    ].map(k=>`<div class="kpi-card">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value" style="color:${k.color}">${k.value}</div>
    </div>`).join('');

    // رسم بياني
    renderTradesChart(_trades);

    if (!_trades.length) {
      document.getElementById('tradesTable').innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📋</div>
          <p>لا توجد صفقات مسجلة</p>
          <p style="font-size:12px;margin-top:8px">اضغط "إضافة صفقة" أو افتح تفاصيل أي سهم وستجد زر تسجيل الصفقة</p>
        </div>`;
      return;
    }

    document.getElementById('tradesTable').innerHTML = `
      <table style="width:100%;border-collapse:collapse">
        <thead><tr>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">الرمز</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">الدخول</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">السعر الحالي</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">الربح/خسارة</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">الوقف / الهدف</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">تاريخ الفتح</th>
          <th style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)">إجراء</th>
        </tr></thead>
        <tbody>${_trades.map(tr => {
          const isOpen = tr.status === 'OPEN';
          const pnlPct  = isOpen ? tr.current_pnl_pct : tr.pnl_pct;
          const pnlEgp  = isOpen ? tr.current_pnl_egp  : tr.pnl_egp;
          const curPrice = isOpen ? tr.current_price : tr.exit_price;
          const pnlClass = (pnlPct||0) >= 0 ? 'pnl-positive' : 'pnl-negative';
          return `<tr class="${isOpen?'trade-row-open':'trade-row-closed'}"
                    style="border-bottom:1px solid rgba(255,255,255,0.04)">
            <td style="padding:10px 14px">
              <div style="display:flex;align-items:center;gap:8px">
                <b style="color:var(--accent-blue);font-size:15px;cursor:pointer"
                   onclick="openModal('${tr.symbol}')">${tr.symbol}</b>
                <span style="font-size:10px;padding:1px 6px;border-radius:8px;
                  background:${isOpen?'rgba(104,211,145,0.15)':'rgba(148,163,184,0.1)'};
                  color:${isOpen?'var(--accent-green)':'var(--text-muted)'}">${isOpen?'مفتوحة':'مغلقة'}</span>
              </div>
              ${tr.notes ? `<div style="font-size:10px;color:var(--text-muted);margin-top:2px">${tr.notes}</div>` : ''}
            </td>
            <td style="padding:10px 14px;font-family:Rajdhani,sans-serif;font-weight:700">
              ${fmt(tr.entry_price)} ج
              <div style="font-size:10px;color:var(--text-muted)">${tr.shares} سهم</div>
            </td>
            <td style="padding:10px 14px;font-family:Rajdhani,sans-serif;font-weight:700;
                       color:${isOpen?'var(--text-primary)':'var(--text-muted)'}">
              ${fmt(curPrice)||'—'} ج
            </td>
            <td style="padding:10px 14px">
              ${pnlPct!=null ? `
                <div class="${pnlClass}">${pnlPct>=0?'+':''}${pnlPct}%</div>
                <div style="font-size:11px;color:${(pnlEgp||0)>=0?'var(--accent-green)':'var(--accent-red)'}">${(pnlEgp||0)>=0?'+':''}${(pnlEgp||0).toFixed(0)} ج</div>
              ` : '<span class="muted">—</span>'}
            </td>
            <td style="padding:10px 14px;font-size:11px">
              <span class="red">${fmt(tr.stop_loss)||'—'}</span><br>
              <span class="green" style="font-size:10px">
                ${[tr.near_t1, tr.near_t2, tr.near_t3].filter(Boolean).map((t,i)=>`Q${i+1}: ${fmt(t)}`).join(' | ')||fmt(tr.target1)||'—'}
              </span>
            </td>
            <td style="padding:10px 14px;font-size:11px;color:var(--text-muted)">${tr.opened_at||'—'}</td>
            <td style="padding:10px 14px">
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                ${isOpen ? `
                  <button class="close-btn" onclick="promptCloseTrade(${tr.id}, ${tr.entry_price})">
                    إغلاق
                  </button>` : ''}
                <button class="del-btn" onclick="deleteTrade(${tr.id})">🗑</button>
              </div>
            </td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;
  });
}

function showAddTrade(sym, data) {
  document.getElementById('addTradeModal').style.display = 'flex';
  if (sym) {
    document.getElementById('trSym').value = sym;
    if (data) {
      const t = data.trade || {};
      document.getElementById('trEntry').value  = t.entry_ideal        || data.price || '';
      document.getElementById('trStop').value   = t.stop_loss          || '';
      document.getElementById('trNear1').value  = t.near_targets?.[0]  || '';
      document.getElementById('trNear2').value  = t.near_targets?.[1]  || '';
      document.getElementById('trNear3').value  = t.near_targets?.[2]  || '';
      document.getElementById('trT1').value     = t.targets?.[0]       || '';
      document.getElementById('addTradeSymInfo').textContent =
        `جودة: ${Math.round(t.trade_quality||0)} | سيولة: ${t.liq_label||''}`;
      calcTradeTotal();
    }
  }
}

function closeAddTrade(e) {
  if (!e || e.target === document.getElementById('addTradeModal'))
    document.getElementById('addTradeModal').style.display = 'none';
}

function fillTradeFromData(sym) {
  const s = ALL_DATA[sym];
  if (!s) return;
  const t = s.analysis?.trade || {};
  document.getElementById('trEntry').value  = t.entry_ideal        || s.price || '';
  document.getElementById('trStop').value   = t.stop_loss          || '';
  document.getElementById('trNear1').value  = t.near_targets?.[0]  || '';
  document.getElementById('trNear2').value  = t.near_targets?.[1]  || '';
  document.getElementById('trNear3').value  = t.near_targets?.[2]  || '';
  document.getElementById('trT1').value     = t.targets?.[0]       || '';
  calcTradeTotal();
}

function calcTradeTotal() {
  const entry  = parseFloat(document.getElementById('trEntry').value)  || 0;
  const shares = parseFloat(document.getElementById('trShares').value) || 0;
  document.getElementById('trTotal').textContent =
    entry && shares ? `${(entry * shares).toFixed(0)} ج` : '— ج';
}

async function submitTrade() {
  const sym = document.getElementById('trSym').value.trim().toUpperCase();
  const entry = parseFloat(document.getElementById('trEntry').value);
  const shares = parseFloat(document.getElementById('trShares').value);
  if (!sym || !entry || !shares) { alert('الرمز وسعر الدخول وعدد الأسهم مطلوبين'); return; }
  const s = ALL_DATA[sym];
  const t = s?.analysis?.trade || {};
  const body = {
    symbol: sym, entry_price: entry, shares,
    stop_loss:    parseFloat(document.getElementById('trStop').value)  || t.stop_loss,
    near_t1:      parseFloat(document.getElementById('trNear1').value) || t.near_targets?.[0],
    near_t2:      parseFloat(document.getElementById('trNear2').value) || t.near_targets?.[1],
    near_t3:      parseFloat(document.getElementById('trNear3').value) || t.near_targets?.[2],
    target1:      parseFloat(document.getElementById('trT1').value)    || t.targets?.[0],
    trade_quality: t.trade_quality,
    signal_type:  s?.analysis?.signal_type,
    notes:        document.getElementById('trNotes').value,
  };
  try {
    const r = await fetch('/api/trades', { method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const j = await r.json();
    if (j.ok) {
      closeAddTrade();
      switchTab('trades');
    }
  } catch(e) { alert('خطأ: ' + e.message); }
}

async function promptCloseTrade(id, entryPrice) {
  const exitStr = prompt(`سعر الخروج (سعر الدخول: ${entryPrice} ج)`);
  if (!exitStr) return;
  const exit = parseFloat(exitStr);
  if (isNaN(exit)) { alert('سعر غير صحيح'); return; }
  try {
    await fetch('/api/trades/close', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ id, exit_price: exit }) });
    renderTrades();
  } catch(e) { alert('خطأ: ' + e.message); }
}

async function deleteTrade(id) {
  if (!confirm('هل أنت متأكد من حذف الصفقة؟')) return;
  try {
    await fetch('/api/trades/delete', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ id }) });
    renderTrades();
  } catch(e) { alert('خطأ: ' + e.message); }
}

// ── زر "سجّل صفقة" في الـ Modal ──
function addTradeFromModal(sym) {
  const s = ALL_DATA[sym];
  closeModal();
  showAddTrade(sym, s?.analysis);
}

// ══════════════════════════════════════════════════════
// ADX badge helper
// ══════════════════════════════════════════════════════
function adxBadge(adx, label) {
  if (!adx) return '';
  const c = adx >= 40 ? '#00e676' : adx >= 25 ? '#63b3ed' : adx >= 15 ? '#f6e05e' : '#fc8181';
  return `<span class="adx-badge" style="background:${c}18;color:${c};border:1px solid ${c}33"
    title="${label||''}">ADX ${Math.round(adx)}</span>`;
}

// ══════════════════════════════════════════════════════
// vs EGX30 helper
// ══════════════════════════════════════════════════════
function vsEgx30Cell(vs) {
  if (vs == null) return '—';
  const c = vs >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  return `<span style="color:${c};font-size:12px">${vs>=0?'+':''}${vs}%</span>`;
}

// ══════════════════════════════════════════════════════
// Market Breadth
// ══════════════════════════════════════════════════════
let _breadthData = null;

async function fetchBreadth() {
  try {
    const r = await fetchWithTimeout('/api/breadth', 8000);
    const j = await r.json();
    if (j.ok) _breadthData = j;
  } catch(e) {}
}

function renderBreadthBar() {
  const el = document.getElementById('breadthBar');
  if (!el || !_breadthData) return;
  const b = _breadthData;
  const total = b.total || 1;
  const advPct = (b.advancing/total*100).toFixed(1);
  const decPct = (b.declining/total*100).toFixed(1);
  const uncPct = (b.unchanged/total*100).toFixed(1);

  el.innerHTML = `
  <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px">
      <div style="font-size:13px;font-weight:700">
        🌡️ اتجاه السوق: <span style="color:var(--accent-cyan)">${b.market_mood}</span>
      </div>
      <div style="display:flex;gap:16px;font-size:12px">
        <span class="green">▲ ${b.advancing} صاعد (${advPct}%)</span>
        <span class="red">▼ ${b.declining} هابط (${decPct}%)</span>
        <span class="muted">● ${b.unchanged} ثابت</span>
      </div>
    </div>
    <div class="breadth-bar" style="margin-bottom:10px">
      <div class="breadth-adv" style="width:${advPct}%"></div>
      <div class="breadth-unc" style="width:${uncPct}%"></div>
      <div class="breadth-dec" style="width:${decPct}%"></div>
    </div>
    <div style="display:flex;gap:20px;font-size:12px;flex-wrap:wrap">
      <span>RSI متوسط: <b style="color:${(b.avg_rsi||50)<40?'var(--accent-green)':(b.avg_rsi||50)>60?'var(--accent-red)':'var(--text-primary)'}">${b.avg_rsi||'—'}</b></span>
      <span>فوق SMA50: <b>${b.above_sma50_pct}%</b></span>
      <span>فوق SMA200: <b>${b.above_sma200_pct}%</b></span>
      <span>إشارات شراء: <b class="green">${b.buy_signals}</b></span>
      <span>إشارات بيع: <b class="red">${b.sell_signals}</b></span>
      <span>🕐 ${b.entry_time}</span>
    </div>
    ${b.warning ? `<div style="margin-top:8px;padding:6px 10px;background:rgba(246,173,85,0.08);border:1px solid rgba(246,173,85,0.2);border-radius:6px;font-size:12px;color:var(--accent-orange)">${b.warning}</div>` : ''}
  </div>`;
}



// ══════════════════════════════════════════════════════
// Position Size Calculator (في الـ modal)
// ══════════════════════════════════════════════════════
function calcModalPosition(sym) {
  const capital  = parseFloat(document.getElementById('modalCapital')?.value) || 0;
  const riskPct  = parseFloat(document.getElementById('modalRisk')?.value)    || 2;
  const el       = document.getElementById('modalPosResult');
  if (!el || !capital) return;

  const s = ALL_DATA[sym];
  if (!s) return;
  const pd = s.analysis?.position_data;
  if (!pd?.risk_per_share || !pd?.entry) {
    el.innerHTML = '<span class="muted">بيانات غير كافية</span>';
    return;
  }

  const maxRisk  = capital * riskPct / 100;
  const shares   = Math.floor(maxRisk / pd.risk_per_share);
  const cost     = (shares * pd.entry).toFixed(0);
  const pctCap   = (cost / capital * 100).toFixed(1);
  const riskEgp  = (shares * pd.risk_per_share).toFixed(0);

  if (shares <= 0) {
    el.innerHTML = `<span class="red">رأس المال غير كافٍ — الحد الأدنى: ${(pd.risk_per_share * 10).toFixed(0)} ج</span>`;
    return;
  }

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-top:8px">
    <div style="background:var(--bg-secondary);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">الكمية المثالية</div>
      <div class="pos-result">${shares}</div>
      <div style="font-size:10px;color:var(--text-muted)">سهم</div>
    </div>
    <div style="background:var(--bg-secondary);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">إجمالي الاستثمار</div>
      <div class="pos-result" style="font-size:18px">${parseInt(cost).toLocaleString()}</div>
      <div style="font-size:10px;color:var(--text-muted)">${pctCap}% من رأس المال</div>
    </div>
    <div style="background:var(--bg-secondary);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">أقصى خسارة</div>
      <div class="pos-result" style="color:var(--accent-red);font-size:18px">${parseInt(riskEgp).toLocaleString()}</div>
      <div style="font-size:10px;color:var(--text-muted)">${riskPct}% من رأس المال</div>
    </div>
  </div>`;
}

function updatePosSizeHint() {
  // تحديث تلميح Position Size في بطاقات الفرص
  renderOpportunities();
}

// ══════════════════════════════════════════════════════
// AUTOPILOT SYSTEM — الطيار الآلي
// ══════════════════════════════════════════════════════
let _autoLog     = JSON.parse(localStorage.getItem('egx_auto_log') || '[]');
let _autoSettings = {};
let _autoPollTimer = null;

// ── switchTab يشمل autopilot ──
const _baseSwitchTab = switchTab;
function switchTab(tab) {
  const allTabs = ['overview','opportunities','screener','signals','watchlist','market','trades','autopilot','backtest'];
  currentTab = tab;
  document.querySelectorAll('.nav-tab').forEach((t,i) => t.classList.toggle('active', allTabs[i] === tab));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById('view-'+tab);
  if (el) el.classList.add('active');
  if (tab === 'signals')       renderSignals();
  if (tab === 'watchlist')     renderWatchlist();
  if (tab === 'screener')      renderScreener();
  if (tab === 'opportunities') renderOpportunities();
  if (tab === 'market')        renderMarket();
  if (tab === 'trades')        renderTrades();
  if (tab === 'autopilot')     renderAutopilot();
  if (tab === 'backtest')      renderBacktest();
}

// ── تحميل الإعدادات ──
async function loadAutoSettings() {
  try {
    const r = await fetchWithTimeout('/api/settings', 5000);
    const j = await r.json();
    if (j.ok) _autoSettings = j.settings;
  } catch(e) {}
  return _autoSettings;
}

async function saveAutoSettings() {
  const settings = {
    capital:             parseFloat(document.getElementById('set_capital')?.value)   || 10000,
    risk_pct:            parseFloat(document.getElementById('set_risk')?.value)       || 2,
    min_quality:         parseFloat(document.getElementById('set_quality')?.value)    || 70,
    min_rr:              parseFloat(document.getElementById('set_rr')?.value)         || 1.5,
    min_confirm:         parseInt(document.getElementById('set_confirm')?.value)      || 3,
    max_open_trades:     parseInt(document.getElementById('set_maxopen')?.value)      || 5,
    min_adx:             parseFloat(document.getElementById('set_minadx')?.value)     || 20,
    min_rel_vol:         parseFloat(document.getElementById('set_minrelvol')?.value)  || 1.2,
    max_risk_pct:        parseFloat(document.getElementById('set_maxrisk')?.value)    || 8,
    max_consecutive_losses: parseInt(document.getElementById('set_maxconsec')?.value) || 3,
    auto_open:           document.getElementById('set_autoopen')?.dataset.val === 'true',
    auto_close:          document.getElementById('set_autoclose')?.dataset.val === 'true',
    test_mode:           document.getElementById('set_testmode')?.dataset.val === 'true',
  };
  try {
    await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(settings)
    });
    _autoSettings = settings;
    showToast('النظام','✅ تم حفظ الإعدادات','—',0,'#00e676','target','النظام',null);
    // تحديث capital في تاب الفرص
    const capEl = document.getElementById('capitalInput');
    if (capEl) { capEl.value = settings.capital; renderOpportunities(); }
  } catch(e) { alert('خطأ في الحفظ: ' + e.message); }
}

function toggleSetting(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const isOn = el.dataset.val === 'true';
  el.dataset.val = (!isOn).toString();
  el.className = `setting-toggle ${!isOn ? 'on' : 'off'}`;
  el.querySelector('.toggle-dot').style.left = !isOn ? '20px' : '3px';
}

// ── polling الإشارات التلقائية كل 15 ثانية ──
async function pollAutoSignals() {
  try {
    const r = await fetchWithTimeout('/api/auto/signals', 5000);
    const j = await r.json();
    if (j.ok && j.signals.length) {
      j.signals.forEach(sig => {
        // أضف للسجل المحلي
        _autoLog.unshift({ ...sig, seen: false });
        // toast + sound
        const color = sig.action === 'OPEN' ? '#00e676' :
                      sig.action === 'CLOSE_STOP' ? '#ff1744' : '#f6e05e';
        const sound = sig.action === 'OPEN' ? 'entry' :
                      sig.action === 'CLOSE_STOP' ? 'stop' : 'target';
        const label = {
          'OPEN':       '🚀 افتح صفقة جديدة',
          'CLOSE_T1':   '🎯 اجني الهدف 1',
          'CLOSE_T2':   '🎯 اجني الهدف 2',
          'CLOSE_T3':   '🏆 اجني الهدف 3',
          'CLOSE_STOP': '🛑 نفّذ وقف الخسارة',
          'TRAIL_STOP': '📌 حرّك الوقف',
        }[sig.action] || sig.action;
        showToast(sig.symbol, label, sig.price, sig.change_pct, color, sound, '🤖 طيار', sig.trade_quality);
        addToAlertPanel({symbol:sig.symbol,price:sig.price,change:sig.change_pct},
          {label, color, price:sig.price, type:'AUTO_'+sig.action, sourceTag:'🤖 تلقائي', quality:sig.trade_quality});
      });
      // حفظ السجل
      if (_autoLog.length > 200) _autoLog = _autoLog.slice(0,200);
      localStorage.setItem('egx_auto_log', JSON.stringify(_autoLog));
      // تحديث badge
      const unseen = _autoLog.filter(s => !s.seen).length;
      document.getElementById('badgeAuto').textContent = unseen || 0;
      if (unseen > 0) document.getElementById('badgeAuto').style.display = 'inline';
      // إعادة رسم لو التاب مفتوح
      if (currentTab === 'autopilot') renderAutoSignals();
      if (currentTab === 'trades')    renderTrades();
    }
  } catch(e) {}
}

function startAutoPoll() {
  if (_autoPollTimer) clearInterval(_autoPollTimer);
  setTimeout(pollAutoSignals, 5000);
  _autoPollTimer = setInterval(pollAutoSignals, 15000);
}

// ── Render Autopilot ──
async function renderAutopilot() {
  if (!Object.keys(_autoSettings).length) await loadAutoSettings();
  renderAutoSettings();
  renderAutoSignals();
  loadPerformance();
  // mark all as seen
  _autoLog.forEach(s => s.seen = true);
  localStorage.setItem('egx_auto_log', JSON.stringify(_autoLog));
  document.getElementById('badgeAuto').textContent = 0;
}

function renderAutoSettings() {
  const s = _autoSettings;
  document.getElementById('autoSettings').innerHTML = `
    <div class="setting-row">
      <span class="setting-label">رأس المال الكلي</span>
      <input class="setting-input" id="set_capital" value="${s.capital||10000}" type="number"> ج
    </div>
    <div class="setting-row">
      <span class="setting-label">مخاطرة لكل صفقة</span>
      <input class="setting-input" id="set_risk" value="${s.risk_pct||2}" type="number" step="0.5"> %
    </div>
    <div class="setting-row">
      <span class="setting-label">الحد الأدنى للجودة</span>
      <input class="setting-input" id="set_quality" value="${s.min_quality||70}" type="number">
    </div>
    <div class="setting-row">
      <span class="setting-label">الحد الأدنى R:R</span>
      <input class="setting-input" id="set_rr" value="${s.min_rr||1.5}" type="number" step="0.5">
    </div>
    <div class="setting-row">
      <span class="setting-label">الحد الأدنى للتأكيد</span>
      <input class="setting-input" id="set_confirm" value="${s.min_confirm||3}" type="number">
    </div>
    <div class="setting-row">
      <span class="setting-label">أقصى صفقات مفتوحة</span>
      <input class="setting-input" id="set_maxopen" value="${s.max_open_trades||5}" type="number">
    </div>
    <div class="setting-row">
      <span class="setting-label">الحد الأدنى ADX</span>
      <input class="setting-input" id="set_minadx" value="${s.min_adx||20}" type="number" step="1">
    </div>
    <div class="setting-row">
      <span class="setting-label">الحد الأدنى للحجم النسبي</span>
      <input class="setting-input" id="set_minrelvol" value="${s.min_rel_vol||1.2}" type="number" step="0.1">
    </div>
    <div class="setting-row">
      <span class="setting-label">أقصى مخاطرة لكل صفقة</span>
      <input class="setting-input" id="set_maxrisk" value="${s.max_risk_pct||8}" type="number" step="0.5"> %
    </div>
    <div class="setting-row">
      <span class="setting-label">أقصى خسائر متتالية</span>
      <input class="setting-input" id="set_maxconsec" value="${s.max_consecutive_losses||3}" type="number" min="1">
    </div>
    <div class="setting-row">
      <span class="setting-label">فتح صفقات تلقائياً</span>
      <button class="setting-toggle ${s.auto_open?'on':'off'}" id="set_autoopen"
        data-val="${s.auto_open}" onclick="toggleSetting('set_autoopen')">
        <div class="toggle-dot"></div>
      </button>
    </div>
    <div class="setting-row">
      <span class="setting-label">غلق تلقائي (أهداف/وقف)</span>
      <button class="setting-toggle ${s.auto_close?'on':'off'}" id="set_autoclose"
        data-val="${s.auto_close}" onclick="toggleSetting('set_autoclose')">
        <div class="toggle-dot"></div>
      </button>
    </div>
    <div class="setting-row" style="background:rgba(246,224,94,0.05);border-radius:8px;padding:8px;margin-top:4px">
      <span class="setting-label" style="color:var(--accent-yellow)">🧪 وضع الاختبار (السوق مغلق)</span>
      <button class="setting-toggle ${s.test_mode?'on':'off'}" id="set_testmode"
        data-val="${s.test_mode||false}" onclick="toggleSetting('set_testmode')">
        <div class="toggle-dot"></div>
      </button>
    </div>`;
}

async function renderBacktest() {
  try {
    const r = await fetch('/api/backtest');
    const j = await r.json();
    if (!j.ok) return;
    const s = j.stats;
    document.getElementById('bt_total').textContent = s.total_signals;
    document.getElementById('bt_winrate').textContent = s.win_rate + '%';
    const pnlEl = document.getElementById('bt_pnl');
    pnlEl.textContent = s.total_pnl + ' ج';
    pnlEl.style.color = s.total_pnl >= 0 ? 'var(--accent-green)' : '#ff1744';
    document.getElementById('bt_factor').textContent = s.profit_factor;

    // جدول آخر الإشارات
    let html = '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:var(--bg-card);font-weight:700">';
    html += '<th style="padding:6px 8px;text-align:right">السهم</th>';
    html += '<th style="padding:6px 8px;text-align:right">الدخول</th>';
    html += '<th style="padding:6px 8px;text-align:right">الخروج</th>';
    html += '<th style="padding:6px 8px;text-align:right">P&L</th>';
    html += '<th style="padding:6px 8px;text-align:right">النتيجة</th>';
    html += '<th style="padding:6px 8px;text-align:right">السبب</th>';
    html += '<th style="padding:6px 8px;text-align:right">ADX</th>';
    html += '<th style="padding:6px 8px;text-align:right">الجودة</th></tr></thead><tbody>';
    for (const sig of j.recent) {
      const isWin = sig.result === 'WIN';
      const color = isWin ? 'var(--accent-green)' : '#ff1744';
      html += `<tr style="border-bottom:1px solid var(--border)">
        <td style="padding:5px 8px;font-weight:700">${sig.symbol}</td>
        <td style="padding:5px 8px">${sig.entry_price || '-'}</td>
        <td style="padding:5px 8px">${sig.exit_price || '-'}</td>
        <td style="padding:5px 8px;color:${color}">${sig.pnl || 0}</td>
        <td style="padding:5px 8px;color:${color};font-weight:700">${sig.result}</td>
        <td style="padding:5px 8px">${sig.exit_reason || '-'}</td>
        <td style="padding:5px 8px">${sig.adx || '-'}</td>
        <td style="padding:5px 8px">${sig.trade_quality || '-'}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('backtestTable').innerHTML = html;
  } catch(e) { document.getElementById('backtestTable').innerHTML = '<div style="padding:20px;color:var(--accent-red)">خطأ في تحميل الباك تيست</div>'; }
}

function renderAutoSignals() {
  const el = document.getElementById('autoSignalsList');
  if (!el) return;
  const log = _autoLog.slice(0, 50);
  if (!log.length) {
    el.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🤖</div>
      <p>لا توجد إشارات بعد</p>
      <p style="font-size:12px;margin-top:8px;color:var(--text-muted)">
        النظام يراقب السوق كل 30 ثانية ويرسل إشارة عند تحقق الشروط
      </p>
    </div>`;
    return;
  }

  const actionColors = {
    'OPEN':       '#00e676', 'CLOSE_T1':  '#f6e05e',
    'CLOSE_T2':   '#f6e05e', 'CLOSE_T3':  '#f6e05e',
    'CLOSE_STOP': '#ff1744', 'TRAIL_STOP':'#63b3ed',
  };
  const actionLabels = {
    'OPEN':       '🚀 افتح صفقة',    'CLOSE_T1':   '🎯 اجني الهدف 1',
    'CLOSE_T2':   '🎯 اجني الهدف 2', 'CLOSE_T3':   '🏆 اجني الهدف 3',
    'CLOSE_STOP': '🛑 نفّذ الوقف',   'TRAIL_STOP':  '📌 حرّك الوقف',
  };

  el.innerHTML = log.map((sig, idx) => {
    const color = actionColors[sig.action] || '#94a3b8';
    const label = actionLabels[sig.action] || sig.action;
    const textId = `sigtext_${idx}`;
    return `
    <div class="signal-card ${sig.action}" style="opacity:${sig.seen?0.8:1}">
      <div class="signal-header">
        <div class="signal-sym">${sig.symbol}</div>
        <div class="signal-action" style="color:${color}">${label}</div>
        <div style="margin-right:auto;display:flex;gap:8px;align-items:center">
          ${sig.trade_quality ? `<span style="font-family:Rajdhani,sans-serif;font-size:13px;font-weight:700;color:${qualColor(sig.trade_quality)}">${Math.round(sig.trade_quality)}</span>` : ''}
          <span class="signal-time">${sig.time || ''} ${sig.date || ''}</span>
        </div>
      </div>
      ${sig.action === 'OPEN' ? `
      <div class="signal-body">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px">
          <div style="text-align:center;background:var(--bg-card);border-radius:6px;padding:6px">
            <div style="font-size:10px;color:var(--text-muted)">الدخول</div>
            <div style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700;color:var(--accent-cyan)">${fmt(sig.entry)}</div>
          </div>
          <div style="text-align:center;background:var(--bg-card);border-radius:6px;padding:6px">
            <div style="font-size:10px;color:var(--text-muted)">الكمية</div>
            <div style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700">${sig.shares} سهم</div>
          </div>
          <div style="text-align:center;background:var(--bg-card);border-radius:6px;padding:6px">
            <div style="font-size:10px;color:var(--text-muted)">الوقف</div>
            <div style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700;color:var(--accent-red)">${fmt(sig.stop)}</div>
          </div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
          ${[1,2,3].map(i => sig[`near_t${i}`] ? `
          <div style="background:rgba(104,211,145,0.08);border:1px solid rgba(104,211,145,0.2);border-radius:6px;padding:4px 10px;font-size:11px">
            هدف ${i}: <b class="green">${fmt(sig[`near_t${i}`])}</b>
            <span class="cyan">(+${sig[`near_p${i}`]||0}%)</span>
            — ${[sig.q1,sig.q2,sig.q3][i-1]||0} سهم
          </div>` : '').join('')}
        </div>
      </div>` : `
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">${sig.reason||''}</div>`}

      <!-- نص قابل للنسخ -->
      <div class="signal-text" id="${textId}">${sig.text||''}</div>
      <button class="copy-btn" onclick="copySignal('${textId}',this)">
        📋 نسخ للحافظة — انقله لشركة الوساطة
      </button>
    </div>`;
  }).join('');
}

function copySignal(textId, btn) {
  const text = document.getElementById(textId)?.textContent || '';
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('copied');
    btn.textContent = '✅ تم النسخ!';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = '📋 نسخ للحافظة — انقله لشركة الوساطة';
    }, 2000);
  }).catch(() => {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = '✅ تم النسخ!';
    setTimeout(() => { btn.innerHTML = '📋 نسخ للحافظة — انقله لشركة الوساطة'; }, 2000);
  });
}

async function triggerTest() {
  try {
    // فعّل وضع الاختبار تلقائياً
    const r = await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({test_mode: true})
    });
    // أطلق إشارات تجريبية
    const r2 = await fetchWithTimeout('/api/test/trigger', 10000, {method:'POST'});
    const j  = await r2.json();
    if (j.ok) {
      showToast('النظام', `🧪 ${j.msg}`, 0, null, '#f6e05e', 'target', 'اختبار', null);
      // استدع pollAutoSignals فوراً
      await pollAutoSignals();
      renderAutoSignals();
    } else {
      alert(j.error || 'خطأ في الاختبار');
    }
  } catch(e) {
    alert('خطأ: ' + e.message);
  }
}

function clearAutoLog() {
  if (!confirm('هل أنت متأكد من مسح سجل الإشارات؟')) return;
  _autoLog = [];
  localStorage.removeItem('egx_auto_log');
  document.getElementById('badgeAuto').textContent = 0;
  renderAutoSignals();
}

// ── تحليل الأداء ──
async function loadPerformance() {
  try {
    const r = await fetchWithTimeout('/api/performance', 8000);
    const j = await r.json();
    const el = document.getElementById('perfAnalysis');
    if (!el) return;
    if (!j.ok) {
      el.innerHTML = `<div style="font-size:12px;color:var(--text-muted);padding:10px">
        ${j.msg || 'لا توجد صفقات مغلقة بعد للتحليل'}
      </div>`;
      return;
    }
    const pnlColor = j.total_pnl_egp >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
    el.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
        <div style="background:var(--bg-card);border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">نسبة الفوز</div>
          <div style="font-family:Rajdhani,sans-serif;font-size:22px;font-weight:700;color:${j.win_rate>=50?'var(--accent-green)':'var(--accent-red)'}">${j.win_rate}%</div>
        </div>
        <div style="background:var(--bg-card);border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">إجمالي الربح</div>
          <div style="font-family:Rajdhani,sans-serif;font-size:18px;font-weight:700;color:${pnlColor}">${j.total_pnl_egp>=0?'+':''}${j.total_pnl_egp} ج</div>
        </div>
        <div style="background:var(--bg-card);border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">متوسط الربح</div>
          <div style="font-family:Rajdhani,sans-serif;font-size:18px;font-weight:700;color:var(--accent-green)">+${j.avg_win_pct}%</div>
        </div>
        <div style="background:var(--bg-card);border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:var(--text-muted)">متوسط الخسارة</div>
          <div style="font-family:Rajdhani,sans-serif;font-size:18px;font-weight:700;color:var(--accent-red)">${j.avg_loss_pct}%</div>
        </div>
      </div>
      <div style="margin-bottom:10px">
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">Expectancy (توقع الربح لكل صفقة)</div>
        <div style="font-family:Rajdhani,sans-serif;font-size:16px;font-weight:700;color:${j.expectancy>=0?'var(--accent-green)':'var(--accent-red)'}">${j.expectancy>=0?'+':''}${j.expectancy}%</div>
      </div>
      ${j.recommendations?.length ? `
      <div style="margin-top:10px">
        <div style="font-size:11px;font-weight:600;margin-bottom:6px;color:var(--accent-yellow)">💡 توصيات النظام</div>
        ${j.recommendations.map(r => `<div style="font-size:11px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04)">${r}</div>`).join('')}
      </div>` : ''}`;
  } catch(e) {
    const el = document.getElementById('perfAnalysis');
    if (el) el.innerHTML = `<div style="font-size:12px;color:var(--accent-red)">خطأ في تحميل التحليل</div>`;
  }
}

// ══════════════════════════════════════════════════════
// Export PDF
// ══════════════════════════════════════════════════════
function exportPDF() {
  // نحضّر صفحة طباعة مخصصة بأفضل الفرص والصفقات المفتوحة
  const top    = TOP_DATA.slice(0, 20);
  const trades = _trades.filter(t => t.status === 'OPEN');
  const now    = new Date().toLocaleString('ar-EG');

  const win = window.open('', '_blank');
  win.document.write(`<!DOCTYPE html>
  <html dir="rtl" lang="ar">
  <head>
    <meta charset="UTF-8">
    <title>تقرير EGX Analyzer — ${now}</title>
    <style>
      body { font-family: 'Cairo', Arial, sans-serif; direction: rtl;
             color: #1a1a2e; margin: 20px; font-size: 13px; }
      h1   { font-size: 20px; color: #1e3a8a; border-bottom: 2px solid #1e3a8a;
             padding-bottom: 8px; }
      h2   { font-size: 15px; color: #1e3a8a; margin: 16px 0 8px; }
      table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
      th    { background: #1e3a8a; color: #fff; padding: 7px 10px;
              text-align: right; font-size: 12px; }
      td    { padding: 6px 10px; border-bottom: 1px solid #e2e8f0; font-size: 12px; }
      tr:nth-child(even) td { background: #f8fafc; }
      .green { color: #16a34a; font-weight: 700; }
      .red   { color: #dc2626; font-weight: 700; }
      .badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 700; }
      .footer { margin-top: 30px; font-size: 11px; color: #94a3b8;
                border-top: 1px solid #e2e8f0; padding-top: 8px; }
    </style>
  </head>
  <body>
    <h1>📊 تقرير محلل البورصة المصرية — EGX Analyzer</h1>
    <p style="color:#64748b;font-size:12px">التاريخ: ${now} | إجمالي الأسهم المحللة: ${Object.keys(ALL_DATA).length}</p>

    <h2>🎯 أفضل ${top.length} فرصة دلوقتي</h2>
    <table>
      <tr>
        <th>الرمز</th><th>السعر</th><th>الإشارة</th><th>الجودة</th>
        <th>الدخول المثالي</th><th>وقف الخسارة</th>
        <th>هدف قريب 1</th><th>هدف قريب 2</th><th>هدف قريب 3</th>
        <th>R:R</th><th>ADX</th><th>RSI</th>
      </tr>
      ${top.map(t => `<tr>
        <td><b>${t.symbol}</b><br><small>${t.name||''}</small></td>
        <td>${fmt(t.price)} ج</td>
        <td>${t.signal||''}</td>
        <td><b>${Math.round(t.trade_quality||0)}</b></td>
        <td class="green"><b>${fmt(t.entry)}</b></td>
        <td class="red">${fmt(t.stop)} (${t.risk_pct||0}%-)</td>
        <td class="green">${fmt(t.near_targets?.[0])} (+${t.near_pcts?.[0]||0}%)</td>
        <td class="green">${fmt(t.near_targets?.[1])} (+${t.near_pcts?.[1]||0}%)</td>
        <td class="green">${fmt(t.near_targets?.[2])} (+${t.near_pcts?.[2]||0}%)</td>
        <td>${t.rr1||0}x</td>
        <td>${t.adx ? Math.round(t.adx) : '—'}</td>
        <td>${t.rsi||'—'}</td>
      </tr>`).join('')}
    </table>

    ${trades.length ? `
    <h2>📋 صفقاتي المفتوحة (${trades.length})</h2>
    <table>
      <tr>
        <th>الرمز</th><th>سعر الدخول</th><th>الأسهم</th>
        <th>السعر الحالي</th><th>الربح/خسارة</th>
        <th>وقف الخسارة</th><th>الأهداف القريبة</th>
      </tr>
      ${trades.map(t => `<tr>
        <td><b>${t.symbol}</b></td>
        <td>${fmt(t.entry_price)} ج</td>
        <td>${t.shares}</td>
        <td>${fmt(t.current_price)||'—'} ج</td>
        <td class="${(t.current_pnl_pct||0)>=0?'green':'red'}">
          ${t.current_pnl_pct!=null?(t.current_pnl_pct>=0?'+':'')+t.current_pnl_pct+'%':'—'}
        </td>
        <td class="red">${fmt(t.stop_loss)||'—'}</td>
        <td>${[t.near_t1,t.near_t2,t.near_t3].filter(Boolean).join(' | ')||'—'}</td>
      </tr>`).join('')}
    </table>` : ''}

    <div class="footer">
      تم إنشاء هذا التقرير بواسطة EGX Analyzer —
      التحليل للأغراض المعلوماتية فقط وليس نصيحة استثمارية
    </div>
  </body>
  </html>`);
  win.document.close();
  setTimeout(() => { win.print(); }, 500);
}

// ══════════════════════════════════════════════════════
// تصدير CSV للصفقات
// ══════════════════════════════════════════════════════
function exportTradesCSV() {
  if (!_trades.length) { alert('لا توجد صفقات للتصدير'); return; }

  const headers = ['الرمز','سعر الدخول','عدد الأسهم','إجمالي الاستثمار',
                   'وقف الخسارة','هدف قريب 1','هدف قريب 2','هدف قريب 3',
                   'هدف بعيد 1','الحالة','سعر الخروج','الربح/خسارة %',
                   'الربح/خسارة ج','تاريخ الفتح','تاريخ الإغلاق','ملاحظات'];

  const rows = _trades.map(t => [
    t.symbol,
    t.entry_price,
    t.shares,
    t.entry_price && t.shares ? (t.entry_price * t.shares).toFixed(2) : '',
    t.stop_loss   || '',
    t.near_t1     || '',
    t.near_t2     || '',
    t.near_t3     || '',
    t.target1     || '',
    t.status === 'OPEN' ? 'مفتوحة' : 'مغلقة',
    t.exit_price  || '',
    t.pnl_pct     != null ? t.pnl_pct + '%' : '',
    t.pnl_egp     != null ? t.pnl_egp + ' ج' : '',
    t.opened_at   || '',
    t.closed_at   || '',
    t.notes       || '',
  ]);

  const BOM  = '\\uFEFF';
  const csv  = BOM + [headers, ...rows]
    .map(r => r.map(v => `"${String(v).replace(/"/g,'""')}"`).join(','))
    .join('\\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `egx_trades_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════
// رسم بياني أداء الصفقات (SVG بدون مكتبات خارجية)
// ══════════════════════════════════════════════════════
function renderTradesChart(trades) {
  const el = document.getElementById('tradesChart');
  if (!el) return;

  const closed = trades.filter(t => t.status === 'CLOSED' && t.pnl_pct != null);
  if (closed.length < 2) { el.style.display = 'none'; return; }

  el.style.display = 'block';

  // حساب الإحصائيات
  const wins    = closed.filter(t => t.pnl_pct > 0);
  const losses  = closed.filter(t => t.pnl_pct <= 0);
  const winRate = Math.round(wins.length / closed.length * 100);
  const avgWin  = wins.length   ? (wins.reduce((s,t)=>s+t.pnl_pct,0)/wins.length).toFixed(1)     : 0;
  const avgLoss = losses.length ? (losses.reduce((s,t)=>s+t.pnl_pct,0)/losses.length).toFixed(1) : 0;
  const totalPnl = closed.reduce((s,t) => s + (t.pnl_egp||0), 0);

  // رسم أعمدة الربح/خسارة لكل صفقة
  const W = 600, H = 160, PAD = 40;
  const maxAbs = Math.max(...closed.map(t => Math.abs(t.pnl_pct)), 1);
  const barW   = Math.max(8, Math.floor((W - PAD*2) / closed.length) - 2);

  const bars = closed.map((t, i) => {
    const x      = PAD + i * ((W - PAD*2) / closed.length);
    const pct    = t.pnl_pct || 0;
    const hgt    = Math.abs(pct) / maxAbs * (H/2 - 10);
    const isPos  = pct >= 0;
    const y      = isPos ? H/2 - hgt : H/2;
    const color  = isPos ? '#68d391' : '#fc8181';
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}"
      width="${barW}" height="${hgt.toFixed(1)}"
      fill="${color}" rx="2" opacity="0.85">
      <title>${t.symbol}: ${pct}%</title>
    </rect>
    <text x="${(x+barW/2).toFixed(1)}" y="${(isPos?y-3:y+hgt+10).toFixed(1)}"
      text-anchor="middle" font-size="9" fill="${color}">${t.symbol}</text>`;
  }).join('');

  // خط الصفر
  const zeroLine = `<line x1="${PAD}" y1="${H/2}" x2="${W-PAD}" y2="${H/2}"
    stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-dasharray="4,4"/>`;

  // cumulative PnL line
  let cum = 0;
  const cumPoints = closed.map((t, i) => {
    cum += (t.pnl_egp || 0);
    const x = PAD + i * ((W - PAD*2) / closed.length) + barW/2;
    const y = H/2 - (cum / Math.max(Math.abs(cum)*2, 1)) * (H/2 - 10);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const cumLine = closed.length > 1
    ? `<polyline points="${cumPoints}" fill="none"
        stroke="var(--accent-yellow)" stroke-width="1.5" opacity="0.6"/>`
    : '';

  el.innerHTML = `
  <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:10px">
      <h3 style="font-size:13px;font-weight:600;color:var(--accent-cyan)">
        📊 أداء الصفقات المغلقة (${closed.length} صفقة)
      </h3>
      <div style="display:flex;gap:16px;font-size:12px">
        <span>نسبة الفوز: <b style="color:var(--accent-green)">${winRate}%</b></span>
        <span>متوسط الربح: <b style="color:var(--accent-green)">+${avgWin}%</b></span>
        <span>متوسط الخسارة: <b style="color:var(--accent-red)">${avgLoss}%</b></span>
        <span>إجمالي: <b style="color:${totalPnl>=0?'var(--accent-green)':'var(--accent-red)'}">
          ${totalPnl>=0?'+':''}${totalPnl.toFixed(0)} ج
        </b></span>
      </div>
    </div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:160px;overflow:visible">
      ${zeroLine}${bars}${cumLine}
      <text x="${PAD-5}" y="${H/2+4}" text-anchor="end" font-size="9"
        fill="rgba(255,255,255,0.3)">0</text>
    </svg>
    <div style="font-size:10px;color:var(--text-muted);margin-top:6px;text-align:center">
      الأعمدة = ربح/خسارة كل صفقة | الخط الأصفر = PnL التراكمي
    </div>
  </div>`;
}

// ══════════════════════════════════════════════════════
// بحث سريع عن سهم
// ══════════════════════════════════════════════════════
function quickSearch(query) {
  query = query.trim().toLowerCase();
  const cards = document.querySelectorAll('.stock-card');
  if (!query) {
    cards.forEach(c => c.style.display = '');
    return;
  }
  cards.forEach(c => {
    const name = (c.getAttribute('data-symbol') || '').toLowerCase();
    const desc = (c.getAttribute('data-name') || '').toLowerCase();
    c.style.display = (name.includes(query) || desc.includes(query)) ? '' : 'none';
  });
}

// ══════════════════════════════════════════════════════
// Keyboard close modal
// ══════════════════════════════════════════════════════
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeAddTrade(); }
  // Ctrl+F أو / لفتح البحث السريع
  if ((e.ctrlKey && e.key === 'f') || (e.key === '/' && !e.target.matches('input,textarea'))) {
    e.preventDefault();
    const sb = document.getElementById('searchBox');
    if (sb) { sb.focus(); sb.select(); }
  }
});

// ══════════════════════════════════════════════════════
// إشعارات سطح المكتب - Desktop Notifications
// ══════════════════════════════════════════════════════
let _desktopNotifEnabled = false;

function requestDesktopNotif() {
  if ('Notification' in window) {
    Notification.requestPermission().then(p => {
      _desktopNotifEnabled = (p === 'granted');
    });
  }
}

function sendDesktopNotif(title, body, icon) {
  if (!_desktopNotifEnabled) return;
  try {
    new Notification(title, { body: body, icon: icon || '', tag: 'egx-signal' });
  } catch(e) {}
}

// طلب الإذن عند أول تفاعل
document.addEventListener('click', function _reqNotif() {
  requestDesktopNotif();
  document.removeEventListener('click', _reqNotif);
}, { once: true });

// ══════════════════════════════════════════════════════
// تنبيه صوتي - Sound Alert
// ══════════════════════════════════════════════════════
let _soundEnabled = true;

function playAlertSound() {
  if (!_soundEnabled) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.1);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.2);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.4);
  } catch(e) {}
}

// ══════════════════════════════════════════════════════
// عداد تنازلي للتحديث التالي
// ══════════════════════════════════════════════════════
let _countdownSec = 0;
let _countdownInterval = null;

function startCountdown(seconds) {
  _countdownSec = seconds;
  if (_countdownInterval) clearInterval(_countdownInterval);
  _countdownInterval = setInterval(() => {
    _countdownSec--;
    const el = document.getElementById('nextRefreshCountdown');
    if (el) {
      if (_countdownSec > 0) {
        el.textContent = `⏱ ${_countdownSec}ث`;
      } else {
        el.textContent = '⏱ جاري التحديث...';
      }
    }
    if (_countdownSec <= 0) {
      clearInterval(_countdownInterval);
    }
  }, 1000);
}

// ══════════════════════════════════════════════════════
// تتبع الإشارات الجديدة (للتنبيه)
// ══════════════════════════════════════════════════════
let _prevSignalKeys = new Set();

function checkNewSignals(data) {
  if (!data) return;
  const newKeys = new Set();
  for (const [sym, info] of Object.entries(data)) {
    const sig = info?.analysis?.signal;
    if (sig && sig !== 'انتظار' && sig !== 'wait') {
      newKeys.add(`${sym}:${sig}`);
    }
  }
  // مقارنة بالإشارات السابقة
  if (_prevSignalKeys.size > 0) {
    for (const key of newKeys) {
      if (!_prevSignalKeys.has(key)) {
        const [sym, sig] = key.split(':');
        // إشارة جديدة!
        playAlertSound();
        sendDesktopNotif('إشارة EGX جديدة', `${sym} — ${sig}`, '');
      }
    }
  }
  _prevSignalKeys = newKeys;
}

// Boot
init();
startAlertPolling();
startAutoPoll();
loadAutoSettings();
checkSecurityStatus();
// بدء عداد التحديث (60 ثانية)
startCountdown(60);
</script>
</body>
</html>

"""


# ══════════════════════════════════════════════════════════════════════════════
# API Routes - مسارات API
# ══════════════════════════════════════════════════════════════════════════════



import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request as FastAPIRequest
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# الموجه (Router)
# API Router
# ═══════════════════════════════════════════════════════════════

router = APIRouter()

# ═══════════════════════════════════════════════════════════════
# مدير البيانات العام (Singleton)
# Global Data Manager
# ═══════════════════════════════════════════════════════════════

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
    password: str = Field(..., min_length=1, description="كلمة المرور")


class SetupRequest(BaseModel):
    """طلب إعداد كلمة المرور لأول مرة"""
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
        return {"sub": "admin", "role": "admin", "mode": "single_user"}

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

    return payload


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
async def get_all_stocks():
    """جلب بيانات جميع الأسهم مع التحليل الفني"""
    dm = get_data_manager()
    age = round(time.time() - _last_fetch_time) if _last_fetch_time else 0
    data = _get_stocks_with_analysis()

    if data:
        return {"ok": True, "loading": False, "count": len(data), "age_sec": age, "data": data}
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
async def get_top_opportunities():
    """جلب أفضل الفرص التجارية"""
    data = _get_stocks_with_analysis()
    scored: List[Dict[str, Any]] = []

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
        if rr1 < 1.5 or liq < 20:
            continue
        tq = t.get("trade_quality", 0) or 0
        prox = t.get("proximity", 0) or 0
        ready = t.get("ready", False)
        scenario = t.get("entry_scenario", "WAIT")
        # ترتيب الأولوية: MARKET (ادخل الآن) +40، NEAR +20، WAIT +0
        scenario_bonus = 40 if scenario == "MARKET" else 20 if scenario == "NEAR" else 0

        # شروط الطيار الآلي (نفس شروط الـ engine تماماً)
        settings_top = load_settings()
        min_q  = settings_top.get("min_quality", 70)
        min_r  = settings_top.get("min_rr", 1.5)
        min_l  = settings_top.get("min_liq", 40)
        min_c  = settings_top.get("min_confirm", 3)
        min_adx_top  = settings_top.get("min_adx", DEFAULT_MIN_ADX)
        min_rv_top   = settings_top.get("min_rel_vol", DEFAULT_MIN_REL_VOL)
        bull_c = (a.get("confirmation") or {}).get("bull_count", 0)
        adx_v  = v.get("adx") or 0
        rel_v  = (v.get("volume", 0) / v.get("avg_vol", 1)) if v.get("avg_vol", 0) > 0 else 0
        prc_v  = v.get("price") or 0
        sma_v  = v.get("sma50") or 0
        price_above_sma50_top = prc_v > sma_v if (prc_v and sma_v) else True

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
async def check_alerts(w: str = Query("", description="رموز الأسهم مفصولة بفاصلة")):
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
    safe_settings = {k: v for k, v in settings.items() if k != "password_hash"}
    safe_settings["password_hash"] = bool(settings.get("password_hash"))
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
    safe_settings = {k: v for k, v in current.items() if k != "password_hash"}
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
async def get_auto_signals():
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
async def test_trigger_signal():
    """اختبار تشغيل إشارة تجريبية"""
    settings = load_settings()
    data = _get_stocks_with_analysis()

    if not data:
        return {"ok": False, "error": "لا توجد بيانات"}

    engine = get_engine()
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

        if st in ("BUY_STRONG", "BUY") and tq >= 60 and rr >= 1.5:
            card = build_signal_card(
                sym, v, a, t, "OPEN",
                "🧪 إشارة تجريبية", settings,
            )
            card["test"] = True

            # إضافة للإشارات
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
        "msg": f"تم إطلاق {len(triggered)} إشارة تجريبية",
    }


# ═══════════════════════════════════════════════════════════════
# 18. GET /api/auto/signals/log — سجل الإشارات
# Signal history
# ═══════════════════════════════════════════════════════════════


@router.get("/api/auto/signals/log")
async def get_signal_log():
    """جلب سجل الإشارات التاريخية"""
    log = load_signals_log()
    return {"ok": True, "log": log, "count": len(log)}


# ═══════════════════════════════════════════════════════════════
# 19. GET /api/performance — تحليل الأداء
# Trading performance analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/performance")
async def get_performance():
    """تحليل أداء التداولات المغلقة"""
    return _analyze_performance()


# ═══════════════════════════════════════════════════════════════
# 20. GET /api/backtest — تحليل الباك تيست
# Backtest analysis
# ═══════════════════════════════════════════════════════════════


@router.get("/api/backtest")
async def get_backtest():
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
    """تسجيل الدخول باستخدام كلمة المرور"""
    settings = load_settings()
    password_hash = settings.get("password_hash")

    # إذا لم يتم تعيين كلمة مرور بعد
    if not password_hash:
        raise HTTPException(
            status_code=403,
            detail="لم يتم تعيين كلمة المرور بعد — استخدم /api/auth/setup أولاً",
        )

    # التحقق من كلمة المرور
    if not verify_password(body.password, password_hash):
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة")

    # إنشاء رمز JWT
    token = create_jwt_token(user_id="admin", role="admin")
    return {"ok": True, "token": token}


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

    # تجزئة كلمة المرور وحفظها
    hashed = hash_password(body.password)
    save_settings({"password_hash": hashed})

    # إنشاء رمز JWT
    token = create_jwt_token(user_id="admin", role="admin")
    return {"ok": True, "token": token, "msg": "تم تعيين كلمة المرور بنجاح"}


# ═══════════════════════════════════════════════════════════════
# 22b. POST /api/auth/set-password — تعيين أو إزالة كلمة المرور
# Set or remove password (unified endpoint for UI)
# ═══════════════════════════════════════════════════════════════


class SetPasswordRequest(BaseModel):
    """تعيين/تغيير/إزالة كلمة المرور"""
    current_password: str = ""
    new_password: str = ""


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

    hashed = hash_password(body.new_password)
    save_settings({"password_hash": hashed})

    token = create_jwt_token(user_id="admin", role="admin")
    return {"ok": True, "token": token, "msg": "تم تعيين كلمة المرور بنجاح"}


# ═══════════════════════════════════════════════════════════════
# 23. GET /api/engine/status — حالة محرك القرار
# Decision engine status
# ═══════════════════════════════════════════════════════════════


@router.get("/api/engine/status")
async def get_engine_status(user: Dict = Depends(get_current_user)):
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


@router.post("/api/engine/start")
async def start_engine(
    body: Optional[EngineModeUpdate] = None,
    user: Dict = Depends(get_current_user),
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
async def stop_engine(user: Dict = Depends(get_current_user)):
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
# FastAPI Application - التطبيق الرئيسي
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

app = FastAPI(
    title="EGX Statistical Analyzer v2",
    description="محلل البورصة المصرية الإحصائي",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(router)

@app.on_event("startup")
async def startup():
    """تهيئة التطبيق عند البدء"""
    global _engine
    _logger = logging.getLogger(__name__)
    _logger.info("=" * 55)
    _logger.info("  EGX Statistical Analyzer v2")
    _logger.info("  محلل البورصة المصرية الإحصائي")
    _logger.info("=" * 55)
    init_db()
    _logger.info("قاعدة البيانات جاهزة")
    _logger.info(RISK_DISCLAIMER)

    # بدء محرك القرار تلقائياً عند تشغيل التطبيق
    try:
        dm = get_data_manager()
        settings = load_settings()
        # ضبط القيم الافتراضية للإعدادات الجديدة
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

@app.on_event("shutdown")
async def shutdown():
    """تنظيف عند الإغلاق"""
    logging.getLogger(__name__).info("جاري إغلاق التطبيق...")


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
