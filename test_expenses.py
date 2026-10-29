import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def _get_category_id(client, token, type_="expense", name=None):
    resp = await client.get(f"/api/v1/categories?type={type_}", headers=auth_headers(token))
    categories = resp.json()["data"]
    if name:
        return next(c["id"] for c in categories if c["name"] == name)
    return categories[0]["id"]


async def test_create_expense_requires_auth(client):
    resp = await client.post("/api/v1/expenses", json={"amount": "100.00", "expense_date": "2026-08-01"})
    assert resp.status_code == 401


async def test_create_and_get_expense(client, capsys):
    token = await register_verify_login(client, capsys, email="exp1@example.com")
    category_id = await _get_category_id(client, token, "expense", "Food & Dining")

    resp = await client.post(
        "/api/v1/expenses",
        json={
            "amount": "340.00",
            "category_id": category_id,
            "merchant": "Swiggy",
            "payment_method": "upi",
            "note": "Dinner",
            "expense_date": "2026-08-10",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["merchant"] == "Swiggy"
    assert body["amount"] == "340.00" or float(body["amount"]) == 340.0
    assert body["category"]["name"] == "Food & Dining"

    get_resp = await client.get(f"/api/v1/expenses/{body['id']}", headers=auth_headers(token))
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["merchant"] == "Swiggy"


async def test_create_expense_rejects_negative_amount(client, capsys):
    token = await register_verify_login(client, capsys, email="exp2@example.com")
    resp = await client.post(
        "/api/v1/expenses",
        json={"amount": "-50", "expense_date": "2026-08-10"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


async def test_create_expense_with_foreign_category_404(client, capsys):
    token_a = await register_verify_login(client, capsys, email="exp3a@example.com")
    token_b = await register_verify_login(client, capsys, email="exp3b@example.com")
    other_category_id = await _get_category_id(client, token_b, "expense")

    resp = await client.post(
        "/api/v1/expenses",
        json={"amount": "100", "category_id": other_category_id, "expense_date": "2026-08-10"},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 404  # can't tag your expense with someone else's category


async def test_update_and_delete_expense(client, capsys):
    token = await register_verify_login(client, capsys, email="exp4@example.com")
    create = await client.post(
        "/api/v1/expenses", json={"amount": "200", "expense_date": "2026-08-10"}, headers=auth_headers(token)
    )
    expense_id = create.json()["data"]["id"]

    update = await client.put(
        f"/api/v1/expenses/{expense_id}", json={"amount": "250", "note": "corrected"}, headers=auth_headers(token)
    )
    assert update.status_code == 200
    assert float(update.json()["data"]["amount"]) == 250.0
    assert update.json()["data"]["note"] == "corrected"

    delete = await client.delete(f"/api/v1/expenses/{expense_id}", headers=auth_headers(token))
    assert delete.status_code == 200

    get_after_delete = await client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers(token))
    assert get_after_delete.status_code == 404


async def test_user_cannot_access_other_users_expense(client, capsys):
    token_a = await register_verify_login(client, capsys, email="exp5a@example.com")
    token_b = await register_verify_login(client, capsys, email="exp5b@example.com")

    create = await client.post(
        "/api/v1/expenses", json={"amount": "999", "expense_date": "2026-08-10"}, headers=auth_headers(token_a)
    )
    expense_id = create.json()["data"]["id"]

    # B cannot read, update, or delete A's expense.
    get_resp = await client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers(token_b))
    assert get_resp.status_code == 404

    put_resp = await client.put(
        f"/api/v1/expenses/{expense_id}", json={"amount": "1"}, headers=auth_headers(token_b)
    )
    assert put_resp.status_code == 404

    del_resp = await client.delete(f"/api/v1/expenses/{expense_id}", headers=auth_headers(token_b))
    assert del_resp.status_code == 404

    # A can still read it fine — nothing was actually deleted.
    still_there = await client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers(token_a))
    assert still_there.status_code == 200


async def test_list_expenses_pagination(client, capsys):
    token = await register_verify_login(client, capsys, email="exp6@example.com")
    for i in range(25):
        await client.post(
            "/api/v1/expenses",
            json={"amount": str(10 + i), "expense_date": "2026-08-01"},
            headers=auth_headers(token),
        )

    page1 = await client.get("/api/v1/expenses?page=1&page_size=10", headers=auth_headers(token))
    assert page1.status_code == 200
    data = page1.json()["data"]
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["page"] == 1

    page3 = await client.get("/api/v1/expenses?page=3&page_size=10", headers=auth_headers(token))
    assert len(page3.json()["data"]["items"]) == 5  # remainder


async def test_list_expenses_filter_by_payment_method(client, capsys):
    token = await register_verify_login(client, capsys, email="exp7@example.com")
    await client.post(
        "/api/v1/expenses",
        json={"amount": "50", "payment_method": "cash", "expense_date": "2026-08-01"},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "60", "payment_method": "upi", "expense_date": "2026-08-01"},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/expenses?payment_method=cash", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["payment_method"] == "cash"


async def test_list_expenses_date_range(client, capsys):
    token = await register_verify_login(client, capsys, email="exp8@example.com")
    await client.post(
        "/api/v1/expenses", json={"amount": "10", "expense_date": "2026-06-01"}, headers=auth_headers(token)
    )
    await client.post(
        "/api/v1/expenses", json={"amount": "20", "expense_date": "2026-08-01"}, headers=auth_headers(token)
    )

    resp = await client.get(
        "/api/v1/expenses?date_from=2026-07-01&date_to=2026-08-31", headers=auth_headers(token)
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    assert float(data["items"][0]["amount"]) == 20.0


async def test_search_expenses_by_merchant(client, capsys):
    token = await register_verify_login(client, capsys, email="exp9@example.com")
    await client.post(
        "/api/v1/expenses",
        json={"amount": "340", "merchant": "Swiggy", "expense_date": "2026-08-01"},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "90", "merchant": "Chai Point", "expense_date": "2026-08-01"},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/expenses/search?q=swig", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["merchant"] == "Swiggy"


async def test_category_summary(client, capsys):
    token = await register_verify_login(client, capsys, email="exp10@example.com")
    food_id = await _get_category_id(client, token, "expense", "Food & Dining")
    transport_id = await _get_category_id(client, token, "expense", "Transport")

    today = dt.date.today().isoformat()
    await client.post(
        "/api/v1/expenses",
        json={"amount": "300", "category_id": food_id, "expense_date": today},
        headers=auth_headers(token),
    )
    await client.post(
        "/api/v1/expenses",
        json={"amount": "100", "category_id": transport_id, "expense_date": today},
        headers=auth_headers(token),
    )

    resp = await client.get("/api/v1/expenses/category-summary", headers=auth_headers(token))
    assert resp.status_code == 200
    rows = resp.json()["data"]
    totals = {r["category_name"]: float(r["total"]) for r in rows}
    assert totals["Food & Dining"] == 300.0
    assert totals["Transport"] == 100.0
    food_row = next(r for r in rows if r["category_name"] == "Food & Dining")
    assert round(food_row["percentage"]) == 75  # 300 / 400


async def test_monthly_trend_returns_requested_bucket_count(client, capsys):
    token = await register_verify_login(client, capsys, email="exp11@example.com")
    resp = await client.get("/api/v1/expenses/monthly?months=3", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 3
