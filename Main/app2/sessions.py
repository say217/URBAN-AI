import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Request
from starlette.responses import Response

from .config import SECRET_KEY, SESSION_TTL_DAYS

COOKIE_NAME = "app2_session"


def _sign(payload: bytes) -> str:
    return hmac.new(SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def create_session_token(email: str) -> str:
    data = {"email": email, "exp": int(time.time()) + SESSION_TTL_DAYS * 86400}
    payload = base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).rstrip(b"=")
    return f"{payload.decode('ascii')}.{_sign(payload)}"


def read_session_token(token: str) -> Optional[str]:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None

    payload = payload_b64.encode("ascii")
    if not hmac.compare_digest(sig, _sign(payload)):
        return None

    try:
        padded = payload + b"=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None

    if data.get("exp", 0) < time.time():
        return None
    return data.get("email")


def set_session_cookie(response: Response, email: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(email),
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        # secure=True should be turned on once the app is served over HTTPS.
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def get_current_user_email(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_session_token(token)