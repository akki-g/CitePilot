import pytest

from app.auth.email import EmailDeliveryNotConfigured, send_verification_email, verification_url
from app.config import Settings


def test_verification_token_is_kept_in_url_fragment():
    url = verification_url(Settings(FRONTEND_URL="https://citepilot.example.com/"), "secret-token")

    assert url == "https://citepilot.example.com#verify=secret-token"
    assert "?verify=" not in url


async def test_unconfigured_email_delivery_fails_instead_of_claiming_success():
    with pytest.raises(EmailDeliveryNotConfigured):
        await send_verification_email(
            Settings(SMTP_HOST="", RESEND_API_KEY=""),
            "reader@example.com",
            "secret-token",
        )
