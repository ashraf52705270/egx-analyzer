"""
اختبارات الوحدة واختبارات API
"""
import sys, os, tempfile, json
from pathlib import Path

# تبديل قاعدة البيانات إلى مؤقتة للاختبارات
TEST_DIR = Path(tempfile.mkdtemp())
os.environ["EGX_DB_PATH"] = str(TEST_DIR / "test.db")
os.environ["EGX_SECRET_KEY"] = "test-secret-key-for-testing-only!!"
os.environ["EGX_CORS_ORIGINS"] = "http://testserver"

import pytest
from fastapi.testclient import TestClient

from database import *
from analysis import *
from main import app

# تهيئة قاعدة البيانات قبل أي اختبار
init_db()

client = TestClient(app)


# ════════════════════════════════════════════
# Database Tests
# ════════════════════════════════════════════

class TestDatabase:
    def test_init_db(self):
        init_db()

    def test_save_and_load_settings(self):
        s = {"min_adx": 25, "min_rel_vol": 1.5}
        save_settings(s)
        loaded = load_settings()
        assert loaded["min_adx"] == 25
        assert loaded["min_rel_vol"] == 1.5

    def test_log_signal(self):
        init_db()
        signal = log_signal({
            "symbol": "TEST.CA",
            "price": 30.0,
            "rsi": 55,
            "signal_type": "BUY",
            "trend": "UP",
            "support": 28.0,
            "resistance": 32.0,
            "stop_loss": 27.0,
            "rr_ratio": 2.5,
            "trade_quality": 80,
            "adx": 25,
            "entry_scenario": "A",
            "volume_ratio": 1.5,
            "sma_trend": "up",
        })
        assert signal is not None
        assert signal.get("id", 0) > 0

    def test_add_and_close_trade(self):
        init_db()
        trade = add_trade({
            "symbol": "TEST2.CA",
            "entry_price": 30.0,
            "stop_loss": 27.0,
            "target": 35.0,
            "shares": 100,
        })
        assert trade is not None
        tid = trade.get("id")

        closed = close_trade(tid, exit_price=35.0, reason="TP")
        assert closed is not None
        assert closed.get("pnl", 0) > 0

    def test_update_signal_result(self):
        init_db()
        signal = log_signal({"symbol": "TEST3.CA", "price": 30.0, "rsi": 55, "signal_type": "BUY", "trend": "UP"})
        sid = signal["id"]
        ok = update_signal_result(sid, result="WIN", pnl=500, pnl_pct=16.67, exit_price=35.0, exit_reason="TP")
        assert ok is True

        with get_session() as session:
            s = session.query(SignalLog).filter_by(id=sid).first()
            assert s is not None
            assert s.result == "WIN"

    def test_sent_signal_tracking(self):
        init_db()
        mark_sent("TEST_SENT.CA", "BUY")
        assert was_sent("TEST_SENT.CA", "BUY") is True
        assert was_sent("OTHER.CA", "SELL") is False

    def test_load_signals_log(self):
        init_db()
        log_signal({"symbol": "LOG_TEST.CA", "price": 30.0, "rsi": 55, "signal_type": "SELL", "trend": "DOWN"})
        signals = load_signals_log(limit=10)
        assert len(signals) >= 1


# ════════════════════════════════════════════
# Analysis Tests
# ════════════════════════════════════════════

class TestAnalysis:
    def test_hash_and_verify_password(self):
        hashed = hash_password("test123")
        assert verify_password("test123", hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_jwt_token_flow(self):
        token = create_jwt_token("admin")
        assert token is not None
        payload = verify_jwt_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"

    def test_jwt_expired_token(self):
        # رمز منتهي الصلاحية
        import jwt as pyjwt
        expired = pyjwt.encode({"sub": "test", "exp": 0}, SECRET_KEY, algorithm=JWT_ALGORITHM)
        payload = verify_jwt_token(expired)
        assert payload is None

    def test_invalid_jwt(self):
        payload = verify_jwt_token("invalid-token-12345")
        assert payload is None

    def test_encrypt_decrypt(self):
        original = {"name": "test", "value": 123}
        pwd = "secret-key-123"
        encrypted = encrypt_json(original, pwd)
        decrypted = decrypt_json(encrypted, pwd)
        assert decrypted == original



# ════════════════════════════════════════════
# API Tests
# ════════════════════════════════════════════

class TestAPI:
    def test_health_endpoint(self):
        resp = client.get("/api/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "ready" in data

    def test_settings_get(self):
        resp = client.get("/api/settings")
        assert resp.status_code == 200

    def test_settings_post(self):
        resp = client.post("/api/settings", json={"min_adx": 30})
        assert resp.status_code == 200
        data = resp.json()
        # المفتاح قد يكون في مستوى مختلف حسب استجابة الـ API
        assert "ok" in data

    def test_auth_setup_and_login(self):
        # أولاً: مسح أي كلمة مرور موجودة مسبقاً
        save_settings({"password_hash": ""})

        # setup
        resp = client.post("/api/auth/setup", json={"password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "token" in data

        # login
        resp = client.post("/api/auth/login", json={"password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data

        # login with wrong password
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 401

        # تنظيف: إزالة كلمة المرور حتى لا تؤثر على باقي الاختبارات
        save_settings({"password_hash": ""})

    def test_engine_endpoints(self):
        # status — لا يحتاج auth
        resp = client.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data

        resp = client.post("/api/engine/stop")
        assert resp.status_code in (200, 503), f"stop failed: {resp.status_code} {resp.text[:200]}"

        resp = client.post("/api/engine/start")
        assert resp.status_code in (200, 503), f"start failed: {resp.status_code} {resp.text[:200]}"

    def test_trades_endpoint(self):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_backtest_endpoint(self):
        resp = client.get("/api/backtest")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_performance_endpoint(self):
        resp = client.get("/api/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_signals_log_endpoint(self):
        resp = client.get("/api/auto/signals/log")
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            data = resp.json()


# ════════════════════════════════════════════
# تنظيف بعد الاختبارات
# ════════════════════════════════════════════

def teardown_module():
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)
