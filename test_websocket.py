"""
Two layers of testing here, deliberately:
1. Unit tests against ws_manager.ConnectionManager directly, with a fake
   WebSocket object — fast, no network, tests the broadcast/prune logic in
   isolation.
2. Real end-to-end tests using starlette.testclient.TestClient, which opens
   an actual WebSocket handshake against the real ASGI app (not mocked).
   These use TestClient for BOTH the HTTP setup calls and the WS connection
   (rather than mixing with the async httpx client fixture used elsewhere)
   specifically to avoid a cross-event-loop hazard: TestClient runs the app
   in its own managed thread/loop, and mixing that with the separate event
   loop the async httpx fixture uses to talk to the same in-memory
   ws_manager singleton risks flaky "attached to a different loop" errors.
   Keeping HTTP+WS on the same TestClient sidesteps that entirely.
"""
import re

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services import ws_manager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


# ---------- Unit tests: ConnectionManager ----------
async def test_send_to_user_delivers_to_all_open_connections():
    mgr = ws_manager.ConnectionManager()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    mgr._connections["user-1"] = [ws_a, ws_b]

    await mgr.send_to_user("user-1", "notification", {"title": "Hi"})

    assert ws_a.sent == [{"type": "notification", "data": {"title": "Hi"}}]
    assert ws_b.sent == [{"type": "notification", "data": {"title": "Hi"}}]


async def test_send_to_user_with_no_connections_is_a_silent_noop():
    mgr = ws_manager.ConnectionManager()
    await mgr.send_to_user("nobody-connected", "notification", {"title": "Hi"})  # must not raise


async def test_dead_connection_is_pruned_not_raised():
    mgr = ws_manager.ConnectionManager()
    dead = FakeWebSocket(fail=True)
    alive = FakeWebSocket()
    mgr._connections["user-1"] = [dead, alive]

    await mgr.send_to_user("user-1", "notification", {"x": 1})  # must not raise despite dead's failure

    assert alive.sent == [{"type": "notification", "data": {"x": 1}}]
    assert mgr.connection_count("user-1") == 1  # dead one pruned


def test_disconnect_removes_user_entry_when_empty():
    mgr = ws_manager.ConnectionManager()
    ws = FakeWebSocket()
    mgr._connections["user-1"] = [ws]
    mgr.disconnect("user-1", ws)
    assert "user-1" not in mgr._connections


async def test_events_never_cross_between_users():
    mgr = ws_manager.ConnectionManager()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    mgr._connections["user-a"] = [ws_a]
    mgr._connections["user-b"] = [ws_b]

    await mgr.send_to_user("user-a", "notification", {"secret": "A's data"})

    assert ws_a.sent
    assert ws_b.sent == []  # user B never receives user A's event


# ---------- End-to-end: real handshake over the real app ----------
def _register_verify_login_sync(client: TestClient, capsys, email: str, password: str = "StrongPass123") -> str:
    client.post("/api/v1/auth/register", json={"full_name": "Test User", "email": email, "password": password})
    captured = capsys.readouterr().out
    match = re.search(r"verification code is: (\d+)", captured)
    assert match, f"OTP not found:\n{captured}"
    code = match.group(1)

    client.post("/api/v1/auth/verify-otp", json={"email": email, "code": code, "purpose": "email_verification"})
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return resp.json()["data"]["access_token"]


def test_ws_rejects_invalid_token(capsys):
    with TestClient(app) as client:
        with pytest.raises(Exception):  # server closes during/just after handshake
            with client.websocket_connect("/api/v1/ws?token=not.a.real.jwt") as ws:
                ws.receive_json()


def test_ws_connects_with_valid_token(capsys):
    with TestClient(app) as client:
        token = _register_verify_login_sync(client, capsys, "ws1@example.com")
        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            pass  # connecting and cleanly closing without error is the assertion


def test_ws_receives_real_notification_event_end_to_end(capsys):
    """The real integration: lock an account (triggers a real notification
    via notification_service.create_notification), and confirm the
    already-open WebSocket actually receives it — not mocked at any layer."""
    with TestClient(app) as client:
        email = "ws2@example.com"
        token = _register_verify_login_sync(client, capsys, email)

        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            for _ in range(5):
                client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPass1"})

            message = ws.receive_json()
            assert message["type"] == "notification"
            assert message["data"]["type"] == "security"
            assert message["data"]["title"] == "Account locked"


def test_ws_receives_real_transaction_event_end_to_end(capsys):
    with TestClient(app) as client:
        email = "ws3@example.com"
        token = _register_verify_login_sync(client, capsys, email)
        headers = {"Authorization": f"Bearer {token}"}

        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            client.post(
                "/api/v1/expenses",
                json={"amount": "250.00", "merchant": "Live Update Test", "expense_date": "2026-08-01"},
                headers=headers,
            )
            message = ws.receive_json()
            assert message["type"] == "transaction"
            assert message["data"]["kind"] == "expense"
            assert message["data"]["label"] == "Live Update Test"


def test_ws_events_isolated_between_users(capsys):
    """User B's connection must never receive user A's transaction event."""
    with TestClient(app) as client:
        token_a = _register_verify_login_sync(client, capsys, "wsa@example.com")
        token_b = _register_verify_login_sync(client, capsys, "wsb@example.com")
        headers_a = {"Authorization": f"Bearer {token_a}"}

        with client.websocket_connect(f"/api/v1/ws?token={token_b}") as ws_b:
            client.post(
                "/api/v1/expenses",
                json={"amount": "50.00", "merchant": "User A Only", "expense_date": "2026-08-01"},
                headers=headers_a,
            )
            with pytest.raises(Exception):
                ws_b.receive_json(timeout=0.5)
