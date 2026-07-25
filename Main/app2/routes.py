import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db
from .config import MAX_VERIFY_ATTEMPTS, VERIFY_CODE_EXP_MINUTES
from .email_utils import EmailSendError, send_verification_email
from .security import (
    generate_verification_code,
    hash_code,
    hash_password,
    verify_code_hash,
    verify_password,
)
from .sessions import clear_session_cookie, set_session_cookie

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Safe to call repeatedly - CREATE TABLE IF NOT EXISTS. Runs once at import
# so the DB file/schema exists before the first request ever arrives.
db.init_db()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _issue_and_send_code(email: str, purpose: str = "signup") -> None:
    code = generate_verification_code()
    expires_at = (datetime.utcnow() + timedelta(minutes=VERIFY_CODE_EXP_MINUTES)).isoformat()
    db.store_verification_code(email, hash_code(code), expires_at, purpose=purpose)
    send_verification_email(email, code, VERIFY_CODE_EXP_MINUTES)


@router.get("/")
def home(request: Request):
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/signup")
def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    username = username.strip()

    if not EMAIL_RE.match(email):
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Enter a valid email address."}
        )
    if not username:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Username is required."}
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Password must be at least 8 characters."}
        )

    existing = db.get_user_by_email(email)
    if existing and existing["is_verified"]:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": "An account with this email already exists. Try logging in instead.",
            },
        )

    # Creates a new unverified user, or refreshes a still-pending one.
    db.create_or_update_pending_user(email, username, hash_password(password))

    try:
        _issue_and_send_code(email)
    except EmailSendError as exc:
        logger.error("signup: could not email verification code to %s: %s", email, exc)
        return templates.TemplateResponse(
            "verify.html",
            {
                "request": request,
                "email": email,
                "error": f"Your account was created, but we couldn't send the verification email: {exc}",
            },
        )

    return templates.TemplateResponse(
        "verify.html",
        {
            "request": request,
            "email": email,
            "message": f"We sent a verification code to {email}. It expires in {VERIFY_CODE_EXP_MINUTES} minutes.",
        },
    )


@router.get("/verify")
def verify_form(request: Request, email: Optional[str] = None):
    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


@router.post("/verify")
def verify_account(request: Request, email: str = Form(...), code: str = Form(...)):
    email = email.strip().lower()
    code = code.strip()

    user = db.get_user_by_email(email)
    if not user:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": "No pending signup found for this email."},
        )

    if user["is_verified"]:
        response = RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, email)
        return response

    record = db.get_active_code(email, purpose="signup")
    if not record:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": "No active code for this email. Request a new one below."},
        )

    if datetime.fromisoformat(record["expires_at"]) < datetime.utcnow():
        db.consume_code(record["id"])
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": "That code expired. Request a new one below."},
        )

    if record["attempts"] >= MAX_VERIFY_ATTEMPTS:
        db.consume_code(record["id"])
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": "Too many incorrect attempts. Request a new code below."},
        )

    if not verify_code_hash(code, record["code_hash"]):
        db.increment_code_attempts(record["id"])
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": "Incorrect verification code."},
        )

    db.consume_code(record["id"])
    db.mark_user_verified(email)

    response = RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, email)
    return response


@router.post("/resend")
def resend_code(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    user = db.get_user_by_email(email)

    # Same response whether or not the account exists/is already verified,
    # so this endpoint can't be used to probe which emails have accounts.
    generic_message = f"If {email} has a pending signup, a new code was just sent."

    if not user or user["is_verified"]:
        return templates.TemplateResponse(
            "verify.html", {"request": request, "email": email, "message": generic_message}
        )

    try:
        _issue_and_send_code(email)
    except EmailSendError as exc:
        logger.error("resend: could not email verification code to %s: %s", email, exc)
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "error": f"Couldn't send a new code: {exc}"},
        )

    return templates.TemplateResponse(
        "verify.html", {"request": request, "email": email, "message": generic_message}
    )


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    user = db.get_user_by_email(email)

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid email or password."}
        )

    if not user["is_verified"]:
        message = "Your email isn't verified yet."
        try:
            _issue_and_send_code(email)
            message += f" We just sent a fresh code to {email}."
        except EmailSendError:
            message += " Enter the code from your original signup email, or request a new one below."
        return templates.TemplateResponse(
            "verify.html", {"request": request, "email": email, "message": message}
        )

    response = RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, email)
    return response


@router.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response