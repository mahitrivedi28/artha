from tests.helpers import auth_headers, register_verify_login


async def test_default_categories_seeded_on_register(client, capsys):
    token = await register_verify_login(client, capsys, email="cats@example.com")
    resp = await client.get("/api/v1/categories", headers=auth_headers(token))
    assert resp.status_code == 200
    categories = resp.json()["data"]
    assert len(categories) == 10  # 5 expense + 5 income defaults
    assert {c["type"] for c in categories} == {"expense", "income"}
    assert all(c["is_default"] for c in categories)


async def test_filter_categories_by_type(client, capsys):
    token = await register_verify_login(client, capsys, email="catsfilter@example.com")
    resp = await client.get("/api/v1/categories?type=income", headers=auth_headers(token))
    assert resp.status_code == 200
    categories = resp.json()["data"]
    assert len(categories) == 5
    assert all(c["type"] == "income" for c in categories)


async def test_create_custom_category(client, capsys):
    token = await register_verify_login(client, capsys, email="catcreate@example.com")
    resp = await client.post(
        "/api/v1/categories",
        json={"name": "Side Hustle", "type": "income", "icon": "🚀"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["name"] == "Side Hustle"
    assert body["is_default"] is False


async def test_create_category_invalid_type_rejected(client, capsys):
    token = await register_verify_login(client, capsys, email="catbadtype@example.com")
    resp = await client.post(
        "/api/v1/categories", json={"name": "Whatever", "type": "savings"}, headers=auth_headers(token)
    )
    assert resp.status_code == 422


async def test_delete_category(client, capsys):
    token = await register_verify_login(client, capsys, email="catdel@example.com")
    create = await client.post(
        "/api/v1/categories", json={"name": "Temp", "type": "expense"}, headers=auth_headers(token)
    )
    category_id = create.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/categories/{category_id}", headers=auth_headers(token))
    assert resp.status_code == 200

    # Deleting again (already gone) is a clean 404, not a 500.
    resp = await client.delete(f"/api/v1/categories/{category_id}", headers=auth_headers(token))
    assert resp.status_code == 404


async def test_cannot_delete_other_users_category(client, capsys):
    token_a = await register_verify_login(client, capsys, email="catowner@example.com")
    token_b = await register_verify_login(client, capsys, email="catintruder@example.com")

    resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token_a))
    category_id = resp.json()["data"][0]["id"]

    resp = await client.delete(f"/api/v1/categories/{category_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404  # not 403 — existence isn't confirmed to non-owners
