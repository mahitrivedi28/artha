import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def _food_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    return next(c for c in resp.json()["data"] if c["name"] == "Food & Dining")["id"]


async def test_monthly_analytics_returns_12_months(client, capsys):
    token = await register_verify_login(client, capsys, email="an1@example.com")
    year = dt.date.today().year
    resp = await client.get(f"/api/v1/analytics/monthly?year={year}", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 12
    assert [p["month"] for p in data] == list(range(1, 13))


async def test_monthly_analytics_reflects_real_data(client, capsys):
    token = await register_verify_login(client, capsys, email="an2@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "500.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/income", json={"amount": "2000.00", "income_date": today.isoformat()}, headers=auth_headers(token)
    )

    resp = await client.get(f"/api/v1/analytics/monthly?year={today.year}", headers=auth_headers(token))
    data = resp.json()["data"]
    this_month = next(p for p in data if p["month"] == today.month)
    assert this_month["expense"] == "500.00"
    assert this_month["income"] == "2000.00"
    assert this_month["savings"] == "1500.00"


async def test_yearly_analytics_only_returns_years_with_data(client, capsys):
    token = await register_verify_login(client, capsys, email="an3@example.com")
    resp = await client.get("/api/v1/analytics/yearly", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"] == []  # no transactions yet -> no years


async def test_category_analytics_percentages(client, capsys):
    token = await register_verify_login(client, capsys, email="an4@example.com")
    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cats = resp.json()["data"]
    today = dt.date.today()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "300.00", "category_id": cats[0]["id"], "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "700.00", "category_id": cats[1]["id"], "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )

    date_from = today.replace(day=1).isoformat()
    date_to = today.isoformat()
    resp = await client.get(
        f"/api/v1/analytics/category?date_from={date_from}&date_to={date_to}", headers=auth_headers(token)
    )
    data = resp.json()["data"]
    assert len(data) == 2
    percentages = {d["category_name"]: d["percentage"] for d in data}
    assert abs(percentages[cats[0]["name"]] - 30.0) < 0.1
    assert abs(percentages[cats[1]["name"]] - 70.0) < 0.1


async def test_income_vs_expense(client, capsys):
    token = await register_verify_login(client, capsys, email="an5@example.com")
    resp = await client.get("/api/v1/analytics/income-vs-expense?months=3", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["income"]) == 3
    assert len(data["expense"]) == 3


async def test_savings_trend(client, capsys):
    token = await register_verify_login(client, capsys, email="an6@example.com")
    resp = await client.get("/api/v1/analytics/savings?months=4", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 4


async def test_spending_trend_daily_buckets(client, capsys):
    token = await register_verify_login(client, capsys, email="an7@example.com")
    resp = await client.get("/api/v1/analytics/spending-trend?days=7", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 7


async def test_analytics_isolated_per_user(client, capsys):
    token_a = await register_verify_login(client, capsys, email="ana@example.com")
    token_b = await register_verify_login(client, capsys, email="anb@example.com")
    cat_id = await _food_category_id(client, token_a)
    today = dt.date.today()

    await client.post(
        "/api/v1/expenses",
        json={"amount": "999.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token_a),
    )

    resp = await client.get(f"/api/v1/analytics/monthly?year={today.year}", headers=auth_headers(token_b))
    this_month = next(p for p in resp.json()["data"] if p["month"] == today.month)
    assert this_month["expense"] == "0.00"


async def test_analytics_requires_auth(client):
    resp = await client.get("/api/v1/analytics/monthly")
    assert resp.status_code == 401
