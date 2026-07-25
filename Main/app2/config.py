import logging
import os
import secrets
from email.utils import formataddr, parseaddr
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# app2/config.py -> app2 dir -> package dir -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Env var %s=%r is not a valid int, using default %s", name, value, default)
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _clean_sender(raw: str, fallback_addr: str) -> str:
    """
    SMTP "From" headers need a real, well-formed value. A pasted .env line
    like SMTP_SENDER="URBAN AI" <>" is not valid - parseaddr will fail to
    find a usable address, so fall back to SMTP_USER (which Gmail requires
    the From address to match anyway).
    """
    name, addr = parseaddr(raw)
    addr = addr.strip() or fallback_addr
    return formataddr((name, addr)) if name else addr


SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY is not set in .env - using a random key generated for "
        "this process. Every restart will invalidate existing sessions. "
        "Set SECRET_KEY in .env for stable sessions."
    )

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
VERIFY_CODE_EXP_MINUTES = _get_int("VERIFY_CODE_EXP_MINUTES", 10)
SESSION_TTL_DAYS = _get_int("SESSION_TTL_DAYS", 30)
MAX_VERIFY_ATTEMPTS = _get_int("MAX_VERIFY_ATTEMPTS", 5)

DB_PATH = PROJECT_ROOT / "data" / "urbanai.db"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _get_int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS = _get_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = _get_bool("SMTP_USE_SSL", False)
SMTP_SENDER = _clean_sender(os.getenv("SMTP_SENDER", ""), fallback_addr=SMTP_USER)

if not SMTP_USER or not SMTP_PASSWORD:
    logger.warning(
        "SMTP_USER/SMTP_PASSWORD are not set in .env - verification emails "
        "will fail to send until they're configured. For Gmail, SMTP_USER "
        "is your full Gmail address and SMTP_PASSWORD must be a 16-character "
        "Google App Password (not your normal login password); this "
        "requires 2-Step Verification to be enabled on the Google account."
    )