"""
Tests for the security feature set: TOTP-based 2FA, active session
management, the per-user audit log, and authenticated password change.

pyotp is used for real here (not mocked) — it's a pure local library with
no network dependency, so generating a valid code from the returned secret
is genuinely testing the real verification path.
"""
import pyotp

from tests.helpers import auth_headers, register_verify_login


# ---------- TOTP 2FA ----------
async def test_totp_setup_returns_secret_and_qr(client, capsys):
    token = await register_verify_login(client, capsys, email="totp1@example.com")
    resp = await client.post("/api/v1/security/2fa/setup", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["secret"]) >= 16
    assert data["qr_code_data_uri"].startswith("data:image/png;base64,")


async def test_totp_confirm_with_correct_code_enables_2fa_and_returns_backup_codes(client, capsys):
    token = await register_verify_login(client, capsys, email="totp2@example.com")
    setup = await client.post("/api/v1/security/2fa/setup", headers=auth_headers(token))
    secret = setup.json()["data"]["secret"]

    valid_code = pyotp.TOTP(secret).now()
    resp = await client.post("/api/v1/security/2fa/confirm", json={"code": valid_code}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    backup_codes = resp.json()["data"]["backup_codes"]
    assert len(backup_codes) > 0

    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.json()["data"]["user"]["totp_enabled"] is True


async def test_totp_confirm_with_wrong_code_rejected(client, capsys):
    token = await register_verify_login(client, capsys, email="totp3@example.com")
    await client.post("/api/v1/security/2fa/setup", headers=auth_headers(token))

    resp = await client.post("/api/v1/security/2fa/confirm", json={"code": "000000"}, headers=auth_headers(token))
    assert resp.status_code in (400, 401)

    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.json()["data"]["user"]["totp_enabled"] is False  # still not enabled


async def test_totp_disable_requires_correct_password(client, capsys):
    password = "StrongPass123"
    token = await register_verify_login(client, capsys, email="totp4@example.com", password=password)
    setup = await client.post("/api/v1/security/2fa/setup", headers=auth_headers(token))
    secret = setup.json()["data"]["secret"]
    await client.post(
        "/api/v1/security/2fa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=auth_headers(token)
    )

    wrong = await client.post(
        "/api/v1/security/2fa/disable", json={"password": "WrongPass1"}, headers=auth_headers(token)
    )
    assert wrong.status_code == 401

    right = await client.post(
        "/api/v1/security/2fa/disable", json={"password": password}, headers=auth_headers(token)
    )
    assert right.status_code == 200

    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.json()["data"]["user"]["totp_enabled"] is False


# ---------- Sessions ----------
async def test_list_sessions_returns_active_sessions(client, capsys):
    token = await register_verify_login(client, capsys, email="sess1@example.com")
    resp = await client.get("/api/v1/security/sessions", headers=auth_headers(token))
    assert resp.status_code == 200
    sessions = resp.json()["data"]
    assert len(sessions) >= 1
    assert "ip_address" in sessions[0]
    assert "is_current" in sessions[0]


async def test_revoke_other_sessions_leaves_exactly_one(client, capsys):
    email, password = "sess2@example.com", "StrongPass123"
    await register_verify_login(client, capsys, email=email, password=password)
    # Two more independent logins = three sessions total.
    await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login.json()["data"]["access_token"]

    before = await client.get("/api/v1/security/sessions", headers=auth_headers(token))
    assert len(before.json()["data"]) == 3

    resp = await client.post("/api/v1/security/sessions/revoke-others", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["revoked_count"] == 2

    after = await client.get("/api/v1/security/sessions", headers=auth_headers(token))
    assert len(after.json()["data"]) == 1


async def test_cannot_revoke_another_users_session(client, capsys):
    token_a = await register_verify_login(client, capsys, email="sessa@example.com")
    token_b = await register_verify_login(client, capsys, email="sessb@example.com")

    sessions_a = await client.get("/api/v1/security/sessions", headers=auth_headers(token_a))
    session_id = sessions_a.json()["data"][0]["id"]

    resp = await client.delete(f"/api/v1/security/sessions/{session_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404

    # User A's session must still be alive.
    still_there = await client.get("/api/v1/security/sessions", headers=auth_headers(token_a))
    assert session_id in [s["id"] for s in still_there.json()["data"]]


# ---------- Audit log ----------
async def test_audit_log_shows_own_events_only(client, capsys):
    token_a = await register_verify_login(client, capsys, email="audita@example.com")
    token_b = await register_verify_login(client, capsys, email="auditb@example.com")

    # Generate a distinctive event for A only.
    for _ in range(2):
        await client.post("/api/v1/auth/login", json={"email": "audita@example.com", "password": "WrongPass1"})

    log_a = await client.get("/api/v1/security/audit-log", headers=auth_headers(token_a))
    log_b = await client.get("/api/v1/security/audit-log", headers=auth_headers(token_b))

    assert any(e["event_type"] == "login_failed" for e in log_a.json()["data"])
    assert not any(e["event_type"] == "login_failed" for e in log_b.json()["data"])


# ---------- Authenticated password change ----------
async def test_change_password_wrong_current_password_rejected(client, capsys):
    token = await register_verify_login(client, capsys, email="chpw1@example.com", password="StrongPass123")
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WrongOne1", "new_password": "NewStrongPass1"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 401


async def test_change_password_succeeds_and_old_password_stops_working(client, capsys):
    token = await register_verify_login(client, capsys, email="chpw2@example.com", password="StrongPass123")
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "StrongPass123", "new_password": "NewStrongPass1"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    old_login = await client.post("/api/v1/auth/login", json={"email": "chpw2@example.com", "password": "StrongPass123"})
    assert old_login.status_code == 401

    new_login = await client.post("/api/v1/auth/login", json={"email": "chpw2@example.com", "password": "NewStrongPass1"})
    assert new_login.status_code == 200


async def test_change_password_revokes_other_sessions(client, capsys):
    email, password = "chpw3@example.com", "StrongPass123"
    await register_verify_login(client, capsys, email=email, password=password)
    await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login.json()["data"]["access_token"]

    before = await client.get("/api/v1/security/sessions", headers=auth_headers(token))
    assert len(before.json()["data"]) == 3

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "NewStrongPass1"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    after = await client.get("/api/v1/security/sessions", headers=auth_headers(token))
    assert len(after.json()["data"]) < 3  # other sessions revoked


# ---------- Auth required ----------
async def test_security_endpoints_require_auth(client):
    for method, path in [
        ("get", "/api/v1/security/sessions"),
        ("get", "/api/v1/security/audit-log"),
        ("post", "/api/v1/security/2fa/setup"),
    ]:
        resp = await getattr(client, method)(path)
        assert resp.status_code == 401, f"{method.upper()} {path} should require auth"

    resp = await client.post(
        "/api/v1/auth/change-password", json={"current_password": "x", "new_password": "NewStrongPass1"}
    )
    assert resp.status_code == 401
