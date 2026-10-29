import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def _food_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cats = resp.json()["data"]
    food = next(c for c in cats if c["name"] == "Food & Dining")
    return food["id"]


async def _stipend_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=income", headers=auth_headers(token))
    cats = resp.json()["data"]
    return next(c for c in cats if c["name"] == "Stipend")["id"]


async def test_create_budget(client, capsys):
    token = await register_verify_login(client, capsys, email="budget1@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    resp = await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "10000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["monthly_limit"] == "10000.00"
    assert data["spent"] == "0.00"
    assert data["status"] == "on_track"


async def test_budget_rejects_income_category(client, capsys):
    token = await register_verify_login(client, capsys, email="budget2@example.com")
    cat_id = await _stipend_category_id(client, token)
    today = dt.date.today()

    resp = await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "5000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_CATEGORY_TYPE"


async def test_budget_status_transitions_with_spending(client, capsys):
    token = await register_verify_login(client, capsys, email="budget3@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    await client.post(
        "/api/v1/budgets",
        json={
            "category_id": cat_id, "monthly_limit": "1000.00",
            "month": today.month, "year": today.year, "alert_threshold": 80,
        },
        headers=auth_headers(token),
    )

    # Spend 850 -> 85% -> warning
    await client.post(
        "/api/v1/expenses",
        json={"amount": "850.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    resp = await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))
    overview = resp.json()["data"]
    assert overview["budgets"][0]["status"] == "warning"
    assert len(overview["alerts"]) == 1

    # Spend another 200 -> 105% -> exceeded
    await client.post(
        "/api/v1/expenses",
        json={"amount": "200.00", "category_id": cat_id, "expense_date": today.isoformat()},
        headers=auth_headers(token),
    )
    resp = await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))
    overview = resp.json()["data"]
    assert overview["budgets"][0]["status"] == "exceeded"
    assert overview["budgets"][0]["remaining"] == "-50.00"


async def test_budget_upsert_same_category_period_updates_not_duplicates(client, capsys):
    token = await register_verify_login(client, capsys, email="budget4@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "5000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "7000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    resp = await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))
    overview = resp.json()["data"]
    assert len(overview["budgets"]) == 1
    assert overview["budgets"][0]["monthly_limit"] == "7000.00"


async def test_dashboard_surfaces_budget_alerts(client, capsys):
    token = await register_verify_login(client, capsys, email="budget5@example.com")
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

    resp = await client.get("/api/v1/dashboard", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["remaining_budget"] == "100.00"
    assert len(data["budget_alerts"]) == 1
    assert "Food & Dining" in data["budget_alerts"][0]["message"]


async def test_delete_budget(client, capsys):
    token = await register_verify_login(client, capsys, email="budget6@example.com")
    cat_id = await _food_category_id(client, token)
    today = dt.date.today()

    resp = await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token),
    )
    budget_id = resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/budgets/{budget_id}", headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/budgets?month={today.month}&year={today.year}", headers=auth_headers(token))
    assert resp.json()["data"]["budgets"] == []


async def test_user_cannot_delete_other_users_budget(client, capsys):
    token_a = await register_verify_login(client, capsys, email="budgeta@example.com")
    token_b = await register_verify_login(client, capsys, email="budgetb@example.com")
    cat_id = await _food_category_id(client, token_a)
    today = dt.date.today()

    resp = await client.post(
        "/api/v1/budgets",
        json={"category_id": cat_id, "monthly_limit": "1000.00", "month": today.month, "year": today.year},
        headers=auth_headers(token_a),
    )
    budget_id = resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/budgets/{budget_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404
