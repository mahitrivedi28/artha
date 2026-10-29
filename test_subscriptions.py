import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def test_create_and_list_subscription(client, capsys):
    token = await register_verify_login(client, capsys, email="sub1@example.com")
    next_date = (dt.date.today() + dt.timedelta(days=10)).isoformat()

    resp = await client.post(
        "/api/v1/subscriptions",
        json={"name": "Netflix", "icon": "🎬", "amount": "649.00", "billing_cycle": "monthly", "next_payment_date": next_date},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["name"] == "Netflix"
    assert data["days_until_renewal"] == 10

    resp = await client.get("/api/v1/subscriptions", headers=auth_headers(token))
    assert len(resp.json()["data"]) == 1


async def test_invalid_billing_cycle_rejected(client, capsys):
    token = await register_verify_login(client, capsys, email="sub2@example.com")
    next_date = (dt.date.today() + dt.timedelta(days=10)).isoformat()

    resp = await client.post(
        "/api/v1/subscriptions",
        json={"name": "Gym", "amount": "1500.00", "billing_cycle": "daily", "next_payment_date": next_date},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_BILLING_CYCLE"


async def test_summary_normalizes_billing_cycles_to_monthly(client, capsys):
    token = await register_verify_login(client, capsys, email="sub3@example.com")
    next_date = (dt.date.today() + dt.timedelta(days=10)).isoformat()

    # 1200/yr yearly = 100/month equivalent; 100/week weekly = 100*52/12 = 433.33/month; 50/month = 50/month.
    await client.post(
        "/api/v1/subscriptions",
        json={"name": "Yearly Plan", "amount": "1200.00", "billing_cycle": "yearly", "next_payment_date": next_date},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/subscriptions",
        json={"name": "Monthly Plan", "amount": "50.00", "billing_cycle": "monthly", "next_payment_date": next_date},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/subscriptions/summary", headers=auth_headers(token))
    data = resp.json()["data"]
    # 1200/12 + 50 = 100 + 50 = 150.00 exactly
    assert data["monthly_total"] == "150.00"
    assert data["active_count"] == 2


async def test_update_and_delete_subscription(client, capsys):
    token = await register_verify_login(client, capsys, email="sub4@example.com")
    next_date = (dt.date.today() + dt.timedelta(days=5)).isoformat()

    resp = await client.post(
        "/api/v1/subscriptions",
        json={"name": "Spotify", "amount": "119.00", "billing_cycle": "monthly", "next_payment_date": next_date},
        headers=auth_headers(token),
    )
    sub_id = resp.json()["data"]["id"]

    resp = await client.put(f"/api/v1/subscriptions/{sub_id}", json={"is_active": False}, headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False

    resp = await client.delete(f"/api/v1/subscriptions/{sub_id}", headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.get("/api/v1/subscriptions", headers=auth_headers(token))
    assert resp.json()["data"] == []


async def test_renewal_reminder_notification_created(client, capsys):
    token = await register_verify_login(client, capsys, email="sub5@example.com")
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()

    await client.post(
        "/api/v1/subscriptions",
        json={"name": "Amazon Prime", "amount": "299.00", "billing_cycle": "monthly", "next_payment_date": tomorrow},
        headers=auth_headers(token),
    )
    # Listing subscriptions is what triggers the reminder sync.
    await client.get("/api/v1/subscriptions", headers=auth_headers(token))

    resp = await client.get("/api/v1/notifications", headers=auth_headers(token))
    notifications = resp.json()["data"]
    assert any(n["type"] == "subscription_reminder" and "Amazon Prime" in n["message"] for n in notifications)


async def test_user_cannot_modify_other_users_subscription(client, capsys):
    token_a = await register_verify_login(client, capsys, email="suba@example.com")
    token_b = await register_verify_login(client, capsys, email="subb@example.com")
    next_date = (dt.date.today() + dt.timedelta(days=5)).isoformat()

    resp = await client.post(
        "/api/v1/subscriptions",
        json={"name": "Private Sub", "amount": "100.00", "billing_cycle": "monthly", "next_payment_date": next_date},
        headers=auth_headers(token_a),
    )
    sub_id = resp.json()["data"]["id"]

    resp = await client.put(f"/api/v1/subscriptions/{sub_id}", json={"amount": "1.00"}, headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_subscriptions_require_auth(client):
    resp = await client.get("/api/v1/subscriptions")
    assert resp.status_code == 401
