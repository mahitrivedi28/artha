import datetime as dt

import pytest

from tests.helpers import auth_headers, register_verify_login


async def _stipend_category_id(client, token):
    resp = await client.get("/api/v1/categories?type=income", headers=auth_headers(token))
    cats = resp.json()["data"]
    stipend = next(c for c in cats if c["name"] == "Stipend")
    return stipend["id"]


async def test_create_and_list_income(client, capsys):
    token = await register_verify_login(client, capsys, email="income1@example.com")
    cat_id = await _stipend_category_id(client, token)

    resp = await client.post(
        "/api/v1/income",
        json={"amount": "8000.00", "category_id": cat_id, "note": "IBM stipend", "income_date": "2026-07-15"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["amount"] == "8000.00"

    resp = await client.get("/api/v1/income", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


async def test_create_income_rejects_negative_amount(client, capsys):
    token = await register_verify_login(client, capsys, email="income2@example.com")
    resp = await client.post(
        "/api/v1/income",
        json={"amount": "-100.00", "income_date": "2026-07-15"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


async def test_user_cannot_access_other_users_income(client, capsys):
    token_a = await register_verify_login(client, capsys, email="incomea@example.com")
    token_b = await register_verify_login(client, capsys, email="incomeb@example.com")

    resp = await client.post(
        "/api/v1/income", json={"amount": "5000.00", "income_date": "2026-07-01"}, headers=auth_headers(token_a)
    )
    income_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/income/{income_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404  # not 403 — existence itself isn't confirmed to non-owners

    resp = await client.delete(f"/api/v1/income/{income_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_update_income(client, capsys):
    token = await register_verify_login(client, capsys, email="income3@example.com")
    resp = await client.post(
        "/api/v1/income", json={"amount": "1000.00", "income_date": "2026-07-01"}, headers=auth_headers(token)
    )
    income_id = resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/v1/income/{income_id}", json={"amount": "1500.00"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["amount"] == "1500.00"


async def test_income_source_summary(client, capsys):
    token = await register_verify_login(client, capsys, email="income4@example.com")
    cat_id = await _stipend_category_id(client, token)
    await client.post(
        "/api/v1/income",
        json={"amount": "8000.00", "category_id": cat_id, "income_date": "2026-07-15"},
        headers=auth_headers(token),
    )
    resp = await client.get("/api/v1/income/source-summary?year=2026&month=7", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(item["source_name"] == "Stipend" for item in data)


async def test_income_monthly_trend_bucket_count(client, capsys):
    token = await register_verify_login(client, capsys, email="income5@example.com")
    resp = await client.get("/api/v1/income/monthly?months=3", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 3
