import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def test_health_score_neutral_for_brand_new_user(client, capsys):
    """No income, no expenses, no budgets, no goals -> every component
    should be the neutral 50, so total is exactly 50.0."""
    token = await register_verify_login(client, capsys, email="hs1@example.com")
    resp = await client.get("/api/v1/health-score", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["score"] == 50.0
    assert data["grade"] == "C"
    for component in data["components"].values():
        assert component["score"] == 50.0


async def test_health_score_requires_auth(client):
    resp = await client.get("/api/v1/health-score")
    assert resp.status_code == 401


async def test_savings_rate_component_exact_math(client, capsys):
    token = await register_verify_login(client, capsys, email="hs2@example.com")
    today = dt.date.today()

    # Income 10000, expense 5000 -> savings rate 50% -> way above the 30%
    # full-marks threshold -> savings_rate score should clamp to 100.
    await client.post("/api/v1/income", json={"amount": "10000.00", "income_date": today.isoformat()}, headers=auth_headers(token))
    await client.post("/api/v1/expenses", json={"amount": "5000.00", "expense_date": today.isoformat()}, headers=auth_headers(token))

    resp = await client.get("/api/v1/health-score", headers=auth_headers(token))
    savings = resp.json()["data"]["components"]["savings_rate"]
    assert savings["score"] == 100.0
    assert savings["average_savings_rate"] == 50.0


async def test_budget_discipline_component_exact_math(client, capsys):
    token = await register_verify_login(client, capsys, email="hs3@example.com")
    today = dt.date.today()

    cats_resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cats = cats_resp.json()["data"]

    # Budget 2 categories, blow one, stay within the other -> 1/2 = 50%.
    await client.post(
        "/api/v1/budgets",
        json={"category_id": cats[0]["id"], "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/budgets",
        json={"category_id": cats[1]["id"], "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "1500.00", "category_id": cats[0]["id"], "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "200.00", "category_id": cats[1]["id"], "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/health-score", headers=auth_headers(token))
    budget = resp.json()["data"]["components"]["budget_discipline"]
    assert budget["score"] == 50.0
    assert budget["categories_within_budget"] == 1
    assert budget["categories_budgeted"] == 2


async def test_goal_progress_component_full_marks_when_ahead(client, capsys):
    token = await register_verify_login(client, capsys, email="hs4@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=100)).isoformat()
    resp = await client.post(
        "/api/v1/goals", json={"title": "Test Goal", "target_amount": "1000.00", "deadline": deadline}, headers=auth_headers(token)
    )
    goal_id = resp.json()["data"]["id"]
    # Fully funded on day 0 -> massively ahead of schedule -> ratio clamps to 100.
    await client.post(f"/api/v1/goals/{goal_id}/contribute", json={"amount": "1000.00"}, headers=auth_headers(token))

    resp = await client.get("/api/v1/health-score", headers=auth_headers(token))
    goal_component = resp.json()["data"]["components"]["goal_progress"]
    # Goal auto-completed -> no longer "active" -> falls back to neutral (no active goals).
    assert goal_component["score"] == 50.0
    assert goal_component["active_goals"] is None


async def test_expense_control_penalizes_overspend_vs_recent_average(client, capsys):
    token = await register_verify_login(client, capsys, email="hs5@example.com")
    today = dt.date.today()

    def months_ago(n):
        y, m = today.year, today.month - n
        while m <= 0:
            m += 12
            y -= 1
        return dt.date(y, m, min(today.day, 28))

    # 3 prior months at 1000 each -> avg 1000. Current month 2000 -> 100% over -> score clamps to 0.
    for i in range(1, 4):
        await client.post(
            "/api/v1/expenses", json={"amount": "1000.00", "expense_date": months_ago(i).isoformat()}, headers=auth_headers(token)
        )
    await client.post("/api/v1/expenses", json={"amount": "2000.00", "expense_date": today.isoformat()}, headers=auth_headers(token))

    resp = await client.get("/api/v1/health-score", headers=auth_headers(token))
    expense_component = resp.json()["data"]["components"]["expense_control"]
    assert expense_component["score"] == 0.0
    assert expense_component["vs_recent_average_pct"] == 100.0


async def test_health_score_isolated_per_user(client, capsys):
    token_a = await register_verify_login(client, capsys, email="hsa@example.com")
    token_b = await register_verify_login(client, capsys, email="hsb@example.com")
    today = dt.date.today()

    await client.post("/api/v1/income", json={"amount": "50000.00", "income_date": today.isoformat()}, headers=auth_headers(token_a))

    resp_b = await client.get("/api/v1/health-score", headers=auth_headers(token_b))
    savings_b = resp_b.json()["data"]["components"]["savings_rate"]
    assert savings_b["score"] == 50.0  # user B's income is untouched by user A's data
