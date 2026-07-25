import logging
import smtplib
from email.message import EmailMessage

from .config import (
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SENDER,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    """Raised whenever a verification email could not be sent."""


def _build_message(to_email: str, code: str, ttl_minutes: int) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your Urban AI verification code"
    msg["From"] = SMTP_SENDER
    msg["To"] = to_email
    msg.set_content(
        f"Your verification code is: {code}\n\n"
        f"This code expires in {ttl_minutes} minutes. "
        "If you didn't request this, you can safely ignore this email."
    )
    msg.add_alternative(
        f"""\
<html>
  <body style="font-family: Arial, sans-serif; color: #111111;">
    <p>Your verification code is:</p>
    <p style="font-size: 28px; font-weight: 700; letter-spacing: 4px; margin: 12px 0;">{code}</p>
    <p style="color: #555555; font-size: 13px;">
      This code expires in {ttl_minutes} minutes. If you didn't request this, you can safely ignore this email.
    </p>
  </body>
</html>
""",
        subtype="html",
    )
    return msg


def send_verification_email(to_email: str, code: str, ttl_minutes: int) -> None:
    """
    Sends a verification code to any recipient address via SMTP (Gmail by
    default). Raises EmailSendError with a human-readable reason on any
    failure - callers decide how to surface that to the user.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise EmailSendError(
            "Email sending isn't configured on the server yet "
            "(SMTP_USER/SMTP_PASSWORD missing)."
        )

    msg = _build_message(to_email, code, ttl_minutes)

    try:
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.ehlo()
                if SMTP_USE_TLS:
                    server.starttls()
                    server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP auth failed sending to %s: %s", to_email, exc)
        raise EmailSendError(
            "The server's email account rejected the login. For Gmail, "
            "make sure 2-Step Verification is on and SMTP_PASSWORD is a "
            "16-character Google App Password, not the normal account password."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP send failed to %s: %s", to_email, exc)
        raise EmailSendError("Couldn't reach the email server. Try again shortly.") from exc