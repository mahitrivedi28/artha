import re


def extract_otp(captured_text: str, email: str) -> str:
    """The dev-mode email fallback (app/services/email_service.py) prints
    '[DEV EMAIL] To: <email> | Subject: ...' blocks. Scope the search to the
    block for this specific recipient so two users registering in the same
    test don't cross-match each other's codes."""
    blocks = captured_text.split("[DEV EMAIL]")
    for block in blocks:
        if f"To: {email} " in block or block.strip().startswith(f"To: {email}"):
            match = re.search(r"verification code is: (\d+)", block)
            if match:
                return match.group(1)
    raise AssertionError(f"OTP not found in captured output for {email}:\n{captured_text}")


def extract_reset_token(captured_text: str, email: str) -> str:
    blocks = captured_text.split("[DEV EMAIL]")
    for block in blocks:
        if f"To: {email} " in block or block.strip().startswith(f"To: {email}"):
            match = re.search(r"reset token is: (\S+)", block)
            if match:
                return match.group(1)
    raise AssertionError(f"Reset token not found in captured output for {email}:\n{captured_text}")


async def register_verify_login(client, capsys, email="user@example.com", password="StrongPass123") -> str:
    """Returns a bearer access token for a freshly created, verified, logged-in user."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Test User", "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    code = extract_otp(capsys.readouterr().out, email)

    resp = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code, "purpose": "email_verification"}
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
