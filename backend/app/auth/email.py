import asyncio
import html
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.auth.security import hash_secret
from app.config import Settings
from app.logging import get_logger


log = get_logger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when a configured provider does not accept the message."""


class EmailDeliveryNotConfigured(EmailDeliveryError):
    """Raised when no outbound provider is configured."""


@dataclass(frozen=True)
class EmailDelivery:
    provider: str
    message_id: str | None = None


def verification_url(settings: Settings, token: str) -> str:
    # A fragment is not sent in HTTP requests or Referer headers. The frontend
    # exchanges the single-use token with the API after loading.
    return f"{settings.FRONTEND_URL.rstrip('/')}#verify={token}"


async def send_verification_email(
    settings: Settings,
    recipient: str,
    token: str,
) -> EmailDelivery:
    url = verification_url(settings, token)
    if settings.RESEND_API_KEY:
        return await _send_with_resend(settings, recipient, url, token)
    if settings.SMTP_HOST:
        message = _verification_message(settings, recipient, url)
        try:
            await asyncio.to_thread(_send_smtp_message, settings, message)
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("auth.email.smtp_failed", error=type(exc).__name__)
            raise EmailDeliveryError("Verification email could not be delivered") from exc
        return EmailDelivery(provider="smtp")

    log.warning("auth.email.not_configured", recipient=recipient, url=url)
    raise EmailDeliveryNotConfigured("Outbound verification email is not configured")


def _verification_message(settings: Settings, recipient: str, url: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Verify your CitePilot email"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(
        "Welcome to CitePilot. Verify your email by opening this link:\n\n"
        f"{url}\n\n"
        f"This single-use link expires in {settings.EMAIL_VERIFICATION_TTL_HOURS} hours."
    )
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        "<h2>Verify your CitePilot email</h2>"
        "<p>Open the secure, single-use link below to activate your account.</p>"
        f'<p><a href="{safe_url}">Verify email</a></p>'
        f"<p>This link expires in {settings.EMAIL_VERIFICATION_TTL_HOURS} hours.</p>",
        subtype="html",
    )
    return message


async def _send_with_resend(
    settings: Settings,
    recipient: str,
    url: str,
    token: str,
) -> EmailDelivery:
    if not settings.SMTP_FROM_EMAIL:
        raise EmailDeliveryNotConfigured("SMTP_FROM_EMAIL must contain a verified sender")
    safe_url = html.escape(url, quote=True)
    payload = {
        "from": settings.SMTP_FROM_EMAIL,
        "to": [recipient],
        "subject": "Verify your CitePilot email",
        "text": (
            "Welcome to CitePilot. Verify your email using this single-use link:\n\n"
            f"{url}\n\nThis link expires in {settings.EMAIL_VERIFICATION_TTL_HOURS} hours."
        ),
        "html": (
            "<h2>Verify your CitePilot email</h2>"
            "<p>Open the secure, single-use link below to activate your account.</p>"
            f'<p><a href="{safe_url}">Verify email</a></p>'
            f"<p>This link expires in {settings.EMAIL_VERIFICATION_TTL_HOURS} hours.</p>"
        ),
        "tags": [{"name": "category", "value": "email_verification"}],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Idempotency-Key": f"verify-{hash_secret(token)}",
                },
                json=payload,
            )
        response.raise_for_status()
        message_id = response.json().get("id")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("auth.email.resend_failed", error=type(exc).__name__)
        raise EmailDeliveryError("Verification email could not be delivered") from exc
    return EmailDelivery(provider="resend", message_id=message_id)


def _send_smtp_message(settings: Settings, message: EmailMessage) -> None:
    smtp_class = smtplib.SMTP_SSL if settings.SMTP_USE_SSL else smtplib.SMTP
    with smtp_class(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
