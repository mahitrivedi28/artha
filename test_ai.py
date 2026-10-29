"""
These tests mock app.ai.gemini_client rather than calling the real Gemini
API — the correct approach for unit-testing an external LLM integration
(no network flakiness, no API cost, deterministic assertions), and also the
only option here since this sandbox has no route to Google's API and no
real key configured. What IS verified for real: prompt construction pulls
actual DB numbers, responses are parsed/validated correctly, data never
crosses between users, and the AI_UNAVAILABLE path works when Gemini fails.
"""
import datetime as dt

import pytest

from app.ai.gemini_client import GeminiUnavailable
from tests.helpers import auth_headers, register_verify_login


async def _make_goal(client, token, target="10000.00", days=100):
    deadline = (dt.date.today() + dt.timedelta(days=days)).isoformat()
    resp = await client.post(
        "/api/v1/goals", json={"title": "Laptop", "target_amount": target, "deadline": deadline}, headers=auth_headers(token)
    )
    return resp.json()["data"]["id"]


# ---------- Goal plan ----------
async def test_goal_plan_uses_real_numbers_in_prompt(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai1@example.com")
    goal_id = await _make_goal(client, token, target="10000.00", days=100)

    captured = {}

    async def fake_generate_json(system_instructions, user_prompt, **kwargs):
        captured["prompt"] = user_prompt
        return {
            "categories_to_reduce": ["Food & Dining"],
            "possible_monthly_savings": "500.00",
            "budget_adjustments": ["Cut dining out twice a week"],
            "spending_recommendations": ["Cook at home more"],
            "goal_strategy": "Save consistently each month.",
            "explanation": "You need ₹100/day to hit your goal.",
        }

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_json", fake_generate_json)

    resp = await client.post("/api/v1/ai/goal-plan", json={"goal_id": goal_id}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # The real Python-computed number (10000/100 = exactly 100.00) must appear
    # in what was sent to the model, not something the model made up.
    assert "100.00" in captured["prompt"]
    assert data["based_on"]["required_daily_saving"] == "100.00"
    assert data["categories_to_reduce"] == ["Food & Dining"]


async def test_goal_plan_returns_503_when_gemini_unavailable(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai2@example.com")
    goal_id = await _make_goal(client, token)

    async def fake_generate_json(*args, **kwargs):
        raise GeminiUnavailable("GEMINI_API_KEY is not configured.")

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_json", fake_generate_json)

    resp = await client.post("/api/v1/ai/goal-plan", json={"goal_id": goal_id}, headers=auth_headers(token))
    assert resp.status_code == 503
    assert resp.json()["error_code"] == "AI_UNAVAILABLE"


async def test_goal_plan_requires_owned_goal(client, capsys, monkeypatch):
    token_a = await register_verify_login(client, capsys, email="ai3a@example.com")
    token_b = await register_verify_login(client, capsys, email="ai3b@example.com")
    goal_id = await _make_goal(client, token_a)

    resp = await client.post("/api/v1/ai/goal-plan", json={"goal_id": goal_id}, headers=auth_headers(token_b))
    assert resp.status_code == 404


# ---------- Chat ----------
async def test_chat_includes_users_real_financial_context(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai4@example.com")
    cat_resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    cat_id = cat_resp.json()["data"][0]["id"]
    today = dt.date.today().isoformat()
    await client.post(
        "/api/v1/expenses", json={"amount": "777.00", "category_id": cat_id, "expense_date": today}, headers=auth_headers(token)
    )

    captured = {}

    async def fake_generate_text(system_instructions, user_prompt, **kwargs):
        captured["system"] = system_instructions
        return "You've spent ₹777.00 this month so far."

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_text", fake_generate_text)

    resp = await client.post("/api/v1/ai/chat", json={"message": "How much have I spent?"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["reply"] == "You've spent ₹777.00 this month so far."
    assert "777.00" in captured["system"]  # real DB number reached the prompt
    assert len(data["conversation"]) == 2  # user turn + assistant turn persisted


async def test_chat_history_isolated_per_user(client, capsys, monkeypatch):
    token_a = await register_verify_login(client, capsys, email="ai5a@example.com")
    token_b = await register_verify_login(client, capsys, email="ai5b@example.com")

    async def fake_generate_text(*args, **kwargs):
        return "reply"

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_text", fake_generate_text)

    await client.post("/api/v1/ai/chat", json={"message": "hi"}, headers=auth_headers(token_a))

    resp = await client.get("/api/v1/ai/chat/history", headers=auth_headers(token_b))
    assert resp.json()["data"] == []  # user B sees none of user A's chat


async def test_chat_returns_503_and_does_not_persist_when_gemini_fails(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai6@example.com")

    async def fake_generate_text(*args, **kwargs):
        raise GeminiUnavailable("boom")

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_text", fake_generate_text)

    resp = await client.post("/api/v1/ai/chat", json={"message": "hi"}, headers=auth_headers(token))
    assert resp.status_code == 503

    resp = await client.get("/api/v1/ai/chat/history", headers=auth_headers(token))
    assert resp.json()["data"] == []  # the rolled-back user message shouldn't be persisted either


# ---------- Categorization ----------
async def test_categorize_expense_matches_real_category(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai7@example.com")
    cat_resp = await client.get("/api/v1/categories?type=expense", headers=auth_headers(token))
    categories = cat_resp.json()["data"]
    food_cat = next(c for c in categories if c["name"] == "Food & Dining")

    async def fake_generate_json(system_instructions, user_prompt, **kwargs):
        assert "Food & Dining" in user_prompt  # real category list reached the prompt
        return {"suggested_category": "Food & Dining", "confidence": 0.92, "reason": "Restaurant name detected."}

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_json", fake_generate_json)

    resp = await client.post(
        "/api/v1/ai/categorize-expense", json={"merchant": "Swiggy"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["suggested_category"] == "Food & Dining"
    assert data["matched_category_id"] == food_cat["id"]


async def test_categorize_expense_handles_unmatched_suggestion(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ai8@example.com")

    async def fake_generate_json(*args, **kwargs):
        return {"suggested_category": "Nonexistent Category", "confidence": 0.5, "reason": "Guess."}

    monkeypatch.setattr("app.services.ai_service.gemini_client.generate_json", fake_generate_json)

    resp = await client.post(
        "/api/v1/ai/categorize-expense", json={"merchant": "Mystery Shop"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["matched_category_id"] is None  # doesn't fabricate a match


async def test_ai_endpoints_require_auth(client):
    resp = await client.post("/api/v1/ai/chat", json={"message": "hi"})
    assert resp.status_code == 401
    resp = await client.post("/api/v1/ai/categorize-expense", json={"merchant": "x"})
    assert resp.status_code == 401
