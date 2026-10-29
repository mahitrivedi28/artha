"""
Tests for scheduled background jobs.

The jobs are called directly rather than through APScheduler — the
scheduler is disabled in tests (SCHEDULER_ENABLED defaults False) on
purpose, since cron ticks firing mid-test-run against the test database
would make the suite non-deterministic. What's being tested here is the
job *logic*; that APScheduler can run a coroutine on a cron trigger is
the library's responsibility, not this project's.
"""
import datetime as dt

import pytest

from app.services import jobs_service
from tests.helpers import auth_headers, register_verify_login


async def _make_subscription(client, token, name, amount, cycle, next_date):
    resp = await client.post(
        "/api/v1/subscriptions",
        json={
            "name": name, "amount": amount, "billing_cycle": cycle,
            "next_payment_date": next_date.isoformat(),
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


# ---------- Date advancement ----------

def test_advance_date_weekly():
    assert jobs_service._advance_date(dt.date(2026, 3, 10), "weekly") == dt.date(2026, 3, 17)


def test_advance_date_monthly():
    assert jobs_service._advance_date(dt.date(2026, 3, 10), "monthly") == dt.date(2026, 4, 10)


def test_advance_date_monthly_clamps_short_month():
    """A subscription billed on the 31st must land on the 30th in a 30-day
    month, not crash or silently skip the month."""
    assert jobs_service._advance_date(dt.date(2026, 3, 31), "monthly") == dt.date(2026, 4, 30)


def test_advance_date_monthly_rolls_over_year():
    assert jobs_service._advance_date(dt.date(2026, 12, 15), "monthly") == dt.date(2027, 1, 15)


def test_advance_date_yearly_handles_leap_day():
    """29 Feb + 1 year doesn't exist in a non-leap year — must clamp to the
    28th rather than raising ValueError and killing the whole job run."""
    assert jobs_service._advance_date(dt.date(2028, 2, 29), "yearly") == dt.date(2029, 2, 28)


# ---------- Subscription auto-conversion ----------

async def test_due_subscription_becomes_a_real_expense(client, capsys):
    token = await register_verify_login(client, capsys, email="job1@example.com")
    today = dt.date.today()
    await _make_subscription(client, token, "Netflix", "649.00", "monthly", today)

    resp = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["expenses_created"] == 1

    expenses = await client.get("/api/v1/expenses", headers=auth_headers(token))
    items = expenses.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["merchant"] == "Netflix"
    assert items[0]["amount"] == "649.00"


async def test_subscription_job_is_idempotent(client, capsys):
    """The single most important property: running twice must not
    double-charge the user's ledger."""
    token = await register_verify_login(client, capsys, email="job2@example.com")
    today = dt.date.today()
    await _make_subscription(client, token, "Spotify", "119.00", "monthly", today)

    first = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))
    second = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))

    assert first.json()["data"]["expenses_created"] == 1
    assert second.json()["data"]["expenses_created"] == 0  # nothing left due

    expenses = await client.get("/api/v1/expenses", headers=auth_headers(token))
    assert expenses.json()["data"]["total"] == 1  # still exactly one charge


async def test_subscription_job_advances_next_payment_date(client, capsys):
    token = await register_verify_login(client, capsys, email="job3@example.com")
    today = dt.date.today()
    await _make_subscription(client, token, "Prime", "299.00", "monthly", today)

    await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))

    subs = await client.get("/api/v1/subscriptions", headers=auth_headers(token))
    next_date = dt.date.fromisoformat(subs.json()["data"][0]["next_payment_date"])
    assert next_date > today


async def test_subscription_job_catches_up_on_missed_periods(client, capsys):
    """A subscription three weeks overdue (server was down, user inactive)
    should generate all three missed charges, not just one."""
    token = await register_verify_login(client, capsys, email="job4@example.com")
    three_weeks_ago = dt.date.today() - dt.timedelta(days=21)
    await _make_subscription(client, token, "Gym", "500.00", "weekly", three_weeks_ago)

    resp = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))
    created = resp.json()["data"]["expenses_created"]
    assert created >= 3  # 21 days / 7-day cycle

    expenses = await client.get("/api/v1/expenses", headers=auth_headers(token))
    assert expenses.json()["data"]["total"] == created


async def test_future_subscription_is_not_charged_early(client, capsys):
    token = await register_verify_login(client, capsys, email="job5@example.com")
    next_week = dt.date.today() + dt.timedelta(days=7)
    await _make_subscription(client, token, "Future Thing", "100.00", "monthly", next_week)

    resp = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))
    assert resp.json()["data"]["expenses_created"] == 0

    expenses = await client.get("/api/v1/expenses", headers=auth_headers(token))
    assert expenses.json()["data"]["total"] == 0


async def test_inactive_subscription_is_not_charged(client, capsys):
    token = await register_verify_login(client, capsys, email="job6@example.com")
    today = dt.date.today()
    sub_id = await _make_subscription(client, token, "Paused Sub", "200.00", "monthly", today)
    await client.put(f"/api/v1/subscriptions/{sub_id}", json={"is_active": False}, headers=auth_headers(token))

    resp = await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token))
    assert resp.json()["data"]["expenses_created"] == 0


async def test_subscription_job_only_touches_own_user(client, capsys):
    """User A's subscription job run must not create expenses for user B —
    and the endpoint runs globally, so this is worth pinning down."""
    token_a = await register_verify_login(client, capsys, email="joba@example.com")
    token_b = await register_verify_login(client, capsys, email="jobb@example.com")
    today = dt.date.today()
    await _make_subscription(client, token_a, "A's Sub", "111.00", "monthly", today)

    await client.post("/api/v1/jobs/run/subscriptions", headers=auth_headers(token_a))

    b_expenses = await client.get("/api/v1/expenses", headers=auth_headers(token_b))
    assert b_expenses.json()["data"]["total"] == 0


# ---------- Weekly digest ----------

async def test_weekly_digest_creates_notification(client, capsys, db_session):
    token = await register_verify_login(client, capsys, email="job7@example.com")
    today = dt.date.today()
    await client.post(
        "/api/v1/expenses", json={"amount": "500.00", "expense_date": today.isoformat()}, headers=auth_headers(token)
    )
    await client.post(
        "/api/v1/income", json={"amount": "2000.00", "income_date": today.isoformat()}, headers=auth_headers(token)
    )

    sent = await jobs_service.send_weekly_digests(db_session)
    assert sent >= 1

    notifications = await client.get("/api/v1/notifications", headers=auth_headers(token))
    assert any(n["type"] == "weekly_digest" for n in notifications.json()["data"])


async def test_weekly_digest_skipped_for_inactive_user(client, capsys, db_session):
    """No transactions in the window -> no empty digest notification."""
    await register_verify_login(client, capsys, email="job8@example.com")
    await jobs_service.send_weekly_digests(db_session)

    token = await register_verify_login(client, capsys, email="job8b@example.com")
    notifications = await client.get("/api/v1/notifications", headers=auth_headers(token))
    assert not any(n["type"] == "weekly_digest" for n in notifications.json()["data"])


# ---------- Scheduler wiring ----------

async def test_job_status_endpoint_reachable(client, capsys):
    """Guards against the bug that hit the ws and security routers twice in
    this project: a fully-built router that was never registered in
    main.py. A 404 here means the router isn't wired up at all."""
    token = await register_verify_login(client, capsys, email="job9@example.com")
    resp = await client.get("/api/v1/jobs/status", headers=auth_headers(token))
    assert resp.status_code == 200
    assert "scheduler_running" in resp.json()["data"]


def test_every_router_module_is_registered():
    """Same bug class, caught structurally: every module in app/routers/
    must actually be included in main.py. This would have caught the ws
    and security router misses immediately instead of via failing
    feature tests."""
    import pathlib

    routers_dir = pathlib.Path(__file__).parent.parent / "app" / "routers"
    main_src = (pathlib.Path(__file__).parent.parent / "app" / "main.py").read_text()

    for path in routers_dir.glob("*.py"):
        if path.stem == "__init__":
            continue
        assert f"{path.stem}.router" in main_src, (
            f"app/routers/{path.stem}.py exists but is never registered via "
            f"app.include_router({path.stem}.router, ...) in main.py"
        )


async def test_jobs_endpoints_require_auth(client):
    resp = await client.get("/api/v1/jobs/status")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/jobs/run/subscriptions")
    assert resp.status_code == 401
