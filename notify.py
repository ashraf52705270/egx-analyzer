import os, json, logging, smtplib, secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

logger = logging.getLogger(__name__)

_ENV_BOT_TOKEN = os.getenv("EGX_TELEGRAM_BOT_TOKEN", "")
_ENV_CHAT_ID = os.getenv("EGX_TELEGRAM_CHAT_ID", "")

def _token_and_chat(bot_token=None, chat_id=None):
    """إرجاع (token, chat_id) حسب الأولوية: الباراميتر > DB > env"""
    bt = bot_token or _ENV_BOT_TOKEN
    ci = chat_id or _ENV_CHAT_ID
    return bt, ci

def send_signal(symbol: str, action: str, price: float, reason: str, quality: int = 0,
                bot_token: str = None, chat_id: str = None) -> bool:
    """إرسال إشارة تداول إلى تليجرام"""
    bt, ci = _token_and_chat(bot_token, chat_id)
    if not bt or not ci:
        return False

    emoji = "🟢" if action == "OPEN" else "🔴"
    text = (
        f"{emoji} *{symbol}* — {action}\n"
        f"💰 السعر: {price:.2f}\n"
        f"⭐ الجودة: {quality}\n"
        f"📝 {reason}"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bt}/sendMessage",
            json={"chat_id": ci, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram: تم إرسال إشارة %s", symbol)
            return True
        else:
            logger.warning("Telegram: فشل الإرسال %s — %s", symbol, resp.text)
            return False
    except Exception as e:
        logger.error("Telegram: خطأ في الإرسال %s: %s", symbol, e)
        return False

def send_alert(msg: str, bot_token: str = None, chat_id: str = None) -> bool:
    """إرسال تنبيه عام"""
    bt, ci = _token_and_chat(bot_token, chat_id)
    if not bt or not ci:
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bt}/sendMessage",
            json={"chat_id": ci, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error("Telegram alert: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════
# إرسال الإيميلات (SMTP)
# ═══════════════════════════════════════════════════════════════

def send_email(to: str, subject: str, html_body: str, settings: dict = None) -> bool:
    """إرسال إيميل عبر SMTP — الإعدادات من قاعدة البيانات"""
    try:
        smtp_host = (settings or {}).get("smtp_host") or os.getenv("EGX_SMTP_HOST", "")
        smtp_port = int((settings or {}).get("smtp_port") or os.getenv("EGX_SMTP_PORT", "587"))
        smtp_user = (settings or {}).get("smtp_user") or os.getenv("EGX_SMTP_USER", "")
        smtp_pass = (settings or {}).get("smtp_pass") or os.getenv("EGX_SMTP_PASS", "")
        smtp_from = (settings or {}).get("smtp_from") or os.getenv("EGX_SMTP_FROM", "noreply@egx-analyzer.com")

        if not smtp_host or not smtp_user or not smtp_pass:
            logger.warning("SMTP غير مُهيّأ — لم يتم إرسال الإيميل إلى %s", to)
            return False

        msg = MIMEMultipart("alternative")
        msg["From"] = smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to], msg.as_string())

        logger.info("تم إرسال إيميل إلى %s — %s", to, subject)
        return True
    except Exception as e:
        logger.error("فشل إرسال الإيميل إلى %s: %s", to, e)
        return False


def send_confirmation_email(to: str, token: str, username: str, settings: dict = None) -> bool:
    """إرسال إيميل تأكيد التسجيل"""
    base_url = os.getenv("EGX_BASE_URL", "http://localhost:8780")
    confirm_link = f"{base_url}/api/auth/confirm-email?token={token}"
    html = f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"></head>
<body style="font-family:Cairo,sans-serif;background:#0a0e1a;padding:40px">
<div style="max-width:520px;margin:auto;background:#18202a;border-radius:16px;padding:32px;border:1px solid rgba(99,179,237,0.15)">
<div style="text-align:center;font-size:40px;margin-bottom:12px">📧</div>
<h2 style="color:#fff;text-align:center;margin:0 0 8px;font-size:20px">مرحباً بك في EGX Analyzer</h2>
<p style="color:#94a3b8;text-align:center;margin:0 0 24px;font-size:13px;line-height:1.8">
شكراً لتسجيلك، <b style="color:#e2e8f0">{username}</b>!<br>
يرجى تأكيد بريدك الإلكتروني لتفعيل الحساب.
</p>
<div style="text-align:center;margin:24px 0">
<a href="{confirm_link}" style="display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#63b3ed,#b37aed);color:#fff;border-radius:8px;text-decoration:none;font-size:14px;font-weight:700">🔐 تأكيد البريد الإلكتروني</a>
</div>
<p style="color:#64748b;font-size:11px;text-align:center;margin:20px 0 0;line-height:1.6">
إذا لم تقم بالتسجيل، تجاهل هذا الإيميل.<br>
EGX Analyzer v2 — جميع الحقوق محفوظة © 2026
</p>
</div></body></html>"""
    return send_email(to, "تأكيد التسجيل — EGX Analyzer", html, settings)
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bt}/sendMessage",
            json={"chat_id": ci, "text": f"⚡ {msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False
