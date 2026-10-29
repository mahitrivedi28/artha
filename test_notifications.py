import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def _food_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    return next(c for c in resp.json()["data"] if c["name"] == "Food & Dining")["id"]


async def test_budget_alert_creates_real_notification(client, capsys):
    token = await register_verify_login(client, capsys, email="notif1@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "900.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    # Viewing the budget overview is what triggers the alert -> notification sync.
    await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token))
    notifications = resp.json()["data"]
    assert any(n["type"] == "budget_alert" and "Food & Dining" in n["message"] for n in notifications)


async def test_budget_alert_notification_not_duplicated_on_repeat_view(client, capsys):
    token = await register_verify_login(client, capsys, email="notif2@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "900.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )

    # View the budget overview 3 times.
    for _ in range(3):
        await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token))
    budget_notifications = [n for n in resp.json()["data"] if n["type"] == "budget_alert"]
    assert len(budget_notifications) == 1  # deduped, not spammed


async def test_account_lockout_creates_security_notification(client, capsys):
    token = await register_verify_login(client, capsys, email="notif3@example.com")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "notif3@example.com", "password": "WrongPass1"})

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token))
    notifications = resp.json()["data"]
    assert any(n["type"] == "security" and n["title"] == "Account locked" for n in notifications)


async def test_mark_notification_read(client, capsys):
    token = await register_verify_login(client, capsys, email="notif4@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()
    await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "100.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses", json={"amount": "90.00", "category_id": cat_id, "expense_date": today.isoformat()}, headers=auth_headers(token)
    )
    await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))

    resp = await client.get("/api/v1/notifications?unread_only=true", headers=auth_headers(token))
    notif_id = resp.json()["data"][0]["id"]

    resp = await client.patch(f"/api/v1/notifications/{notif_id}/read", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["is_read"] is True

    resp = await client.get("/api/v1/notifications?unread_only=true", headers=auth_headers(token))
    assert notif_id not in [n["id"] for n in resp.json()["data"]]


async def test_mark_all_read(client, capsys):
    token = await register_verify_login(client, capsys, email="notif5@example.com")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "notif5@example.com", "password": "WrongPass1"})

    resp = await client.post("/api/v1/notifications/read-all", headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.get("/api/v1/notifications/unread-count", headers=auth_headers(token))
    assert resp.json()["data"]["unread_count"] == 0


async def test_notifications_isolated_per_user(client, capsys):
    token_a = await register_verify_login(client, capsys, email="notifa@example.com")
    token_b = await register_verify_login(client, capsys, email="notifb@example.com")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "notifa@example.com", "password": "WrongPass1"})

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token_b))
    assert resp.json()["data"] == []


async def test_cannot_mark_other_users_notification_read(client, capsys):
    token_a = await register_verify_login(client, capsys, email="notifc@example.com")
    token_b = await register_verify_login(client, capsys, email="notifd@example.com")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "notifc@example.com", "password": "WrongPass1"})

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token_a))
    notif_id = resp.json()["data"][0]["id"]

    resp = await client.patch(f"/api/v1/notifications/{notif_id}/read", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_notifications_require_auth(client):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 401
