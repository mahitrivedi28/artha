"""
Two things are tested here, deliberately differently:
1. The dev-mode fallback (SMTP_HOST unset) — tested for REAL, since it's
   just a print statement with no external dependency.
2. The real-SMTP send path — mocked at aiosmtplib.send, the same reasoning
   as mocking the Gemini client: this sandbox has no route to a real mail
   server, and unit tests for an SMTP integration should mock the network
   call regardless (no flaky tests depending on a live mailbox).
"""
import pytest

from app.config import get_settings
from app.services import email_service


async def test_dev_mode_prints_instead_of_sending(capsys):
    assert email_service.is_configured() is False  # no SMTP_HOST in test env

    sent = await email_service.send_email("user@example.com", "Test Subject", "<p>hi</p>", "hi")
    assert sent is False  # False = fell back to console, not actually sent

    captured = capsys.readouterr().out
    assert "[DEV EMAIL]" in captured
    assert "user@example.com" in captured
    assert "Test Subject" in captured


async def test_otp_email_dev_mode_contains_the_real_code(capsys):
    await email_service.send_otp_email("squad@example.com", "Squad", "482913", "email_verification")
    captured = capsys.readouterr().out
    assert "482913" in captured
    assert "squad@example.com" in captured


async def test_password_reset_email_dev_mode_contains_the_real_token(capsys):
    await email_service.send_password_reset_email("squad@example.com", "Squad", "tok_abc123xyz")
    captured = capsys.readouterr().out
    assert "tok_abc123xyz" in captured


async def test_send_email_uses_real_smtp_when_configured(monkeypatch, capsys):
    settings = get_settings()
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service, "settings", settings)

    captured_call = {}

    async def fake_send(message, **kwargs):
        captured_call["to"] = message["To"]
        captured_call["subject"] = message["Subject"]
        captured_call["hostname"] = kwargs.get("hostname")

    import aiosmtplib
    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    sent = await email_service.send_email("user@example.com", "Real Send Test", "<p>hi</p>", "hi")
    assert sent is True  # True = actually went through the SMTP path
    assert captured_call["to"] == "user@example.com"
    assert captured_call["subject"] == "Real Send Test"
    assert captured_call["hostname"] == "smtp.example.com"

    # Dev-mode console fallback must NOT have fired when SMTP is configured.
    assert "[DEV EMAIL]" not in capsys.readouterr().out


async def test_smtp_failure_raises_delivery_error_not_a_silent_success(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service, "settings", settings)

    async def failing_send(message, **kwargs):
        raise ConnectionRefusedError("mail server unreachable")

    import aiosmtplib
    monkeypatch.setattr(aiosmtplib, "send", failing_send)

    with pytest.raises(email_service.EmailDeliveryError):
        await email_service.send_email("user@example.com", "Subject", "<p>hi</p>", "hi")


async def test_registration_succeeds_even_if_email_delivery_fails(monkeypatch, capsys):
    """The most important integration point: a broken mail server must
    never break registration for the user. The OTP still exists in the DB
    and can be resent — it's just not emailed this one time."""
    from tests.helpers import register_verify_login

    settings = get_settings()
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service, "settings", settings)

    async def failing_send(message, **kwargs):
        raise ConnectionRefusedError("mail server down")

    import aiosmtplib
    monkeypatch.setattr(aiosmtplib, "send", failing_send)

    import httpx
    from httpx import ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Test User", "email": "emailfail@example.com", "password": "StrongPass123"},
        )
        assert resp.status_code == 201  # registration still succeeds
