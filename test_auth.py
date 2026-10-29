import re

import pytest

from tests.helpers import extract_otp as _extract_otp, extract_reset_token


async def _register_and_verify(client, capsys, email="Squad@example.com", password="StrongPass123"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Squad", "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    code = _extract_otp(capsys.readouterr().out, email)

    resp = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code, "purpose": "email_verification"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["user"]


# ---------- Registration ----------
async def test_register_creates_unverified_user(client, capsys):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Squad", "email": "Squad@example.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["user"]["is_verified"] is False


async def test_register_duplicate_email_rejected(client, capsys):
    await _register_and_verify(client, capsys, email="dup@example.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Someone Else", "email": "dup@example.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_weak_password_rejected(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Squad", "email": "weak@example.com", "password": "weak"},
    )
    assert resp.status_code == 422


# ---------- OTP / verification ----------
async def test_login_blocked_before_verification(client, capsys):
    email = "unverified@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Squad", "email": email, "password": "StrongPass123"},
    )
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "NOT_VERIFIED"


async def test_wrong_otp_decrements_attempts(client, capsys):
    email = "otp@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Squad", "email": email, "password": "StrongPass123"},
    )
    capsys.readouterr()
    resp = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": "000000", "purpose": "email_verification"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_OTP"


# ---------- Login success ----------
async def test_full_register_verify_login_flow(client, capsys):
    email = "flow@example.com"
    password = "StrongPass123"
    await _register_and_verify(client, capsys, email=email, password=password)

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user"]["email"] == email
    assert "access_token" in data


# ---------- Lockout ----------
async def test_failed_login_reports_attempts_remaining(client, capsys):
    email = "attempts@example.com"
    password = "StrongPass123"
    await _register_and_verify(client, capsys, email=email, password=password)

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPass1"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] == "INVALID_CREDENTIALS"
    assert body["attempts_remaining"] == 4


async def test_account_locks_after_max_failed_attempts(client, capsys):
    email = "lockout@example.com"
    password = "StrongPass123"
    await _register_and_verify(client, capsys, email=email, password=password)

    for _ in range(5):
        resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPass1"})

    assert resp.status_code == 423
    assert resp.json()["error_code"] == "ACCOUNT_LOCKED"

    # Even the CORRECT password is rejected while locked.
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 423


async def test_login_nonexistent_user_returns_generic_error(client):
    resp = await client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "whatever123"})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "INVALID_CREDENTIALS"


# ---------- /me and token isolation ----------
async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_own_data_only(client, capsys):
    email_a = "usera@example.com"
    email_b = "userb@example.com"
    password = "StrongPass123"
    await _register_and_verify(client, capsys, email=email_a, password=password)
    await _register_and_verify(client, capsys, email=email_b, password=password)

    login_a = await client.post("/api/v1/auth/login", json={"email": email_a, "password": password})
    token_a = login_a.json()["data"]["access_token"]

    me_a = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert me_a.status_code == 200
    assert me_a.json()["data"]["user"]["email"] == email_a  # never leaks user B's data


async def test_forged_token_rejected(client):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "INVALID_TOKEN"


# ---------- Password reset ----------
async def test_forgot_password_always_returns_generic_success(client, capsys):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_reset_password_flow_invalidates_old_password(client, capsys):
    email = "reset@example.com"
    old_password = "StrongPass123"
    new_password = "EvenStronger456"
    await _register_and_verify(client, capsys, email=email, password=old_password)

    capsys.readouterr()
    await client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = extract_reset_token(capsys.readouterr().out, email)

    resp = await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_password})
    assert resp.status_code == 200

    old_login = await client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert old_login.status_code == 401

    new_login = await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert new_login.status_code == 200
