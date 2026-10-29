import datetime as dt

from tests.helpers import auth_headers, register_verify_login


async def test_create_goal_rejects_past_deadline(client, capsys):
    token = await register_verify_login(client, capsys, email="goal1@example.com")
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Laptop", "target_amount": "50000.00", "deadline": "2020-01-01"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


async def test_create_and_get_goal(client, capsys):
    token = await register_verify_login(client, capsys, email="goal2@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=180)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Laptop", "icon": "💻", "target_amount": "50000.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    goal = resp.json()["data"]
    assert goal["current_savings"] == "0.00"
    assert goal["remaining_amount"] == "50000.00"
    assert goal["progress_percentage"] == 0.0
    assert goal["status"] == "active"


async def test_contribution_updates_progress(client, capsys):
    token = await register_verify_login(client, capsys, email="goal3@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=100)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Bike", "target_amount": "20000.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/goals/{goal_id}/contribute",
        json={"amount": "5000.00", "note": "first save"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["current_savings"] == "5000.00"
    assert data["remaining_amount"] == "15000.00"
    assert data["progress_percentage"] == 25.0


async def test_contribution_meeting_target_auto_completes_goal(client, capsys):
    token = await register_verify_login(client, capsys, email="goal4@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Emergency Fund", "target_amount": "1000.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/goals/{goal_id}/contribute", json={"amount": "1200.00"}, headers=auth_headers(token)
    )
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["remaining_amount"] == "0.00"  # never negative


async def test_goal_analysis_math(client, capsys):
    token = await register_verify_login(client, capsys, email="goal5@example.com")
    # Exactly 100 days out, 10000 target, no contributions yet.
    deadline = (dt.date.today() + dt.timedelta(days=100)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Vacation", "target_amount": "10000.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/goals/{goal_id}/analysis", headers=auth_headers(token))
    assert resp.status_code == 200
    analysis = resp.json()["data"]
    assert analysis["days_remaining"] == 100
    assert analysis["remaining_amount"] == "10000.00"
    # required_daily_saving = 10000 / 100 = exactly 100.00
    assert analysis["required_daily_saving"] == "100.00"
    assert analysis["on_track"] is False  # no contributions yet -> no rate -> can't project -> not on track


async def test_goal_analysis_reflects_contribution_rate(client, capsys):
    token = await register_verify_login(client, capsys, email="goal6@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=200)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "House Downpayment", "target_amount": "10000.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]

    # Contribute a large amount today -> average monthly rate is high (since
    # months_elapsed floors at 1) -> should project completion well before deadline.
    await client.post(
        f"/api/v1/goals/{goal_id}/contribute", json={"amount": "5000.00"}, headers=auth_headers(token)
    )

    resp = await client.get(f"/api/v1/goals/{goal_id}/analysis", headers=auth_headers(token))
    analysis = resp.json()["data"]
    assert analysis["average_monthly_contribution"] == "5000.00"
    assert analysis["projected_completion_date"] is not None
    assert analysis["on_track"] is True


async def test_goal_analysis_already_complete(client, capsys):
    token = await register_verify_login(client, capsys, email="goal7@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Small Goal", "target_amount": "100.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]
    await client.post(f"/api/v1/goals/{goal_id}/contribute", json={"amount": "100.00"}, headers=auth_headers(token))

    resp = await client.get(f"/api/v1/goals/{goal_id}/analysis", headers=auth_headers(token))
    analysis = resp.json()["data"]
    assert analysis["remaining_amount"] == "0.00"
    assert analysis["on_track"] is True
    assert analysis["projected_completion_date"] == dt.date.today().isoformat()


async def test_user_cannot_access_other_users_goal(client, capsys):
    token_a = await register_verify_login(client, capsys, email="goala@example.com")
    token_b = await register_verify_login(client, capsys, email="goalb@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=30)).isoformat()

    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Private Goal", "target_amount": "500.00", "deadline": deadline},
        headers=auth_headers(token_a),
    )
    goal_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/goals/{goal_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/goals/{goal_id}/contribute", json={"amount": "10.00"}, headers=auth_headers(token_b)
    )
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/goals/{goal_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_delete_goal_cascades_contributions(client, capsys):
    token = await register_verify_login(client, capsys, email="goal8@example.com")
    deadline = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    resp = await client.post(
        "/api/v1/goals",
        json={"title": "Temp Goal", "target_amount": "500.00", "deadline": deadline},
        headers=auth_headers(token),
    )
    goal_id = resp.json()["data"]["id"]
    await client.post(f"/api/v1/goals/{goal_id}/contribute", json={"amount": "50.00"}, headers=auth_headers(token))

    resp = await client.delete(f"/api/v1/goals/{goal_id}", headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.get("/api/v1/goals", headers=auth_headers(token))
    assert resp.json()["data"] == []


async def test_list_goals_requires_auth(client):
    resp = await client.get("/api/v1/goals")
    assert resp.status_code == 401
