from tests.helpers import auth_headers, register_verify_login


async def _food_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cats = resp.json()["data"]
    food = next(c for c in cats if c["name"] == "Food & Dining")
    return food["id"]


async def test_dashboard_requires_auth(client):
    resp = await client.get("/api/v1/dashboard")
    assert resp.status_code == 401


async def test_dashboard_empty_state_for_new_user(client, capsys):
    token = await register_verify_login(client, capsys, email="dash1@example.com")
    resp = await client.get("/api/v1/dashboard", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["monthly_income"] == "0.00"
    assert data["monthly_expense"] == "0.00"
    assert data["monthly_savings"] == "0.00"
    assert data["recent_transactions"] == []


async def test_dashboard_reflects_real_transactions(client, capsys):
    import datetime as dt

    token = await register_verify_login(client, capsys, email="dash2@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today().isoformat()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "340.00", "category_id": cat_id, "merchant": "Swiggy", "expense_date": today},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/income", json={"amount": "8000.00", "income_date": today}, headers=auth_headers(token)
    )

    resp = await client.get("/api/v1/dashboard", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["monthly_expense"] == "340.00"
    assert data["today_expense"] == "340.00"
    assert data["monthly_income"] == "8000.00"
    assert data["monthly_savings"] == "7660.00"
    assert len(data["recent_transactions"]) == 2
    kinds = {t["kind"] for t in data["recent_transactions"]}
    assert kinds == {"expense", "income"}


async def test_dashboard_isolated_per_user(client, capsys):
    import datetime as dt

    token_a = await register_verify_login(client, capsys, email="dasha@example.com")
    token_b = await register_verify_login(client, capsys, email="dashb@example.com")
    today = dt.date.today().isoformat()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "999.00", "merchant": "UserAOnly", "expense_date": today},
        headers=auth_headers(token_a),
    )

    resp_b = await client.get("/api/v1/dashboard", headers=auth_headers(token_b))
    data_b = resp_b.json()["data"]
    assert data_b["monthly_expense"] == "0.00"
    assert data_b["recent_transactions"] == []


async def test_dashboard_category_breakdown_percentages_sum_near_100(client, capsys):
    import datetime as dt

    token = await register_verify_login(client, capsys, email="dash3@example.com")
    cats_resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cats = cats_resp.json()["data"]
    today = dt.date.today().isoformat()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "600.00", "category_id": cats[0]["id"], "expense_date": today},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "400.00", "category_id": cats[1]["id"], "expense_date": today},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/dashboard", headers=auth_headers(token))
    breakdown = resp.json()["data"]["category_breakdown"]
    total_pct = sum(item["percentage"] for item in breakdown)
    assert 99.0 <= total_pct <= 100.5
