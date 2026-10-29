"""
Phase 8: tests that specifically probe the security posture itself, rather
than any one feature's business logic.
"""
import jose.jwt

from tests.helpers import auth_headers, register_verify_login


async def test_security_headers_present_on_every_response(client):
    resp = await client.get("/api/v1/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "permissions-policy" in resp.headers


async def test_security_headers_present_on_error_responses_too(client):
    resp = await client.get("/api/v1/auth/me")  # 401, no token
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_hsts_not_sent_in_development(client):
    """HSTS over plain HTTP in local dev is meaningless and confusing —
    should only appear when ENVIRONMENT=production."""
    resp = await client.get("/api/v1/health")
    assert "strict-transport-security" not in resp.headers


async def test_cors_rejects_unlisted_origin(client):
    resp = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil-attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin != "https://evil-attacker.example"
    assert allow_origin != "*"


async def test_cors_allows_configured_origin(client):
    resp = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5500"


async def test_sql_injection_in_email_field_does_not_break_or_leak(client, capsys):
    """ORM-only queries mean this should behave identically to any other
    nonexistent email — a generic 401, not a 500 or a data leak."""
    payload = "' OR '1'='1"
    resp = await client.post("/api/v1/auth/login", json={"email": f"attacker{payload}@example.com", "password": "x"})
    assert resp.status_code in (401, 422)  # never 500


async def test_sql_injection_in_search_query_param(client, capsys):
    token = await register_verify_login(client, capsys, email="secsql@example.com")
    resp = await client.get("/api/v1/expenses?q='; DROP TABLE users; --", headers=auth_headers(token))
    assert resp.status_code == 200  # handled as a harmless literal search string, not executed as SQL

    # Prove the table wasn't actually dropped — login still works.
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200


async def test_forged_jwt_with_none_algorithm_rejected(client):
    """The classic 'alg: none' JWT bypass attempt — must be rejected outright.
    python-jose's own encode() refuses to create alg=none tokens, so this
    builds the forged token by hand, the way a real attacker's tooling
    would, rather than relying on the library to stop us."""
    import base64
    import json

    def b64url(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64url({"alg": "none", "typ": "JWT"})
    payload = b64url({"sub": "00000000-0000-0000-0000-000000000000", "type": "access"})
    forged = f"{header}.{payload}."

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_jwt_signed_with_wrong_secret_rejected(client, capsys):
    token = await register_verify_login(client, capsys, email="secjwt@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    user_id = me.json()["data"]["user"]["id"]

    forged = jose.jwt.encode({"sub": user_id, "type": "access"}, key="wrong-secret-attacker-guessed", algorithm="HS256")
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_expense_body_cannot_override_user_id(client, capsys):
    """A forged user_id in the request body must be silently ignored —
    identity always comes from the JWT, never from client-supplied data."""
    token = await register_verify_login(client, capsys, email="secuserid@example.com")
    resp = await client.post(
        "/api/v1/expenses",
        json={"amount": "10.00", "expense_date": "2026-01-01", "user_id": "11111111-1111-1111-1111-111111111111"},
        headers=auth_headers(token),
    )
    # Pydantic's extra="forbid" should reject the unexpected field outright.
    assert resp.status_code == 422


async def test_password_never_returned_in_any_response(client, capsys):
    token = await register_verify_login(client, capsys, email="secpw@example.com")
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    body = resp.text.lower()
    assert "hashed_password" not in body
    assert "password" not in resp.json()["data"]["user"]
