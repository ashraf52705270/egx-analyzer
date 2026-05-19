import sys, os, json, logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

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

RISK_DISCLAIMER = """\u26a0\ufe0f"""

TRADE_MODE_AUTO = "auto"

# ── Base ──
Base = declarative_base()

""".replace("\u26a0\ufe0f", "\u26a0\ufe0f \u062a\u0646\u0648\u064a\u0647 \u0645\u062e\u0627\u0637\u0631 \u0645\u0647\u0645") + open(r'C:\Users\ashra\OneDrive\Desktop\New folder\egx_analyzer_fixed.py', encoding='utf-8').read().split('\n')[797:1650]
