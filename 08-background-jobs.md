# ARTHA — Background jobs (scheduler)

Added after the initial 8 phases, alongside email delivery, WebSockets, and account
security. `app/scheduler.py` (APScheduler wiring) + `app/services/jobs_service.py` (the
job logic itself).

## Why

Two things in ARTHA were quietly dependent on a user happening to open a page:

1. **Budget and goal alerts** only fired when `get_budget_overview` / `list_goals` were
   called — i.e. when someone loaded the Budget, Dashboard, or Goals page. A user who
   blew past their food budget and then didn't open the app for a week simply never got
   told. Now a daily job runs the same checks for every active user.
2. **Subscriptions were decorative.** You could record that Netflix bills ₹649 monthly,
   and the app would remind you it was coming — but it never became an actual expense.
   Your spending totals silently excluded every recurring charge you had.

## Jobs

| Job | Schedule | What it does |
|---|---|---|
| `convert_due_subscriptions` | Daily 00:15 | Turns every due subscription into a real `Expense` row and advances `next_payment_date` |
| `refresh_alerts` | Daily 09:00 | Runs budget + goal deadline checks for all active users |
| `weekly_digest` | Mondays 09:05 | "Last 7 days: ₹X in, ₹Y out, saved ₹Z" notification |

Times are staggered deliberately: 00:15 so a subscription is logged on the day it's
actually due with a small buffer after the date rollover; 09:00 for alerts so they land
when someone might plausibly look at their phone rather than at 3am; 09:05 for the digest
so it isn't contending with the alert job for DB connections.

## Idempotency is the whole design constraint

A scheduled job can run twice for the same period — container restart, manual trigger,
retry, or two workers firing the same tick. For most features that's harmless. For
"convert a due subscription into an expense" it is not: a double run would silently
double-charge the user's ledger with money they never spent.

So `convert_due_subscriptions` advances `next_payment_date` **in the same transaction**
that creates the expense. A second run finds nothing due and does nothing — verified
directly in `test_subscription_job_is_idempotent`, which runs the job twice and asserts
exactly one expense exists afterwards.

The advance is also a **loop, not a single step**. A subscription three weeks overdue
(server was down, user inactive) generates all three missed charges rather than silently
skipping them and resuming as if nothing was owed.

Date arithmetic has its own edge cases, each with a test: a subscription billed on the
31st clamps to the 30th in a 30-day month (rather than crashing or skipping), and a
yearly subscription starting 29 Feb clamps to 28 Feb in a non-leap year (rather than
raising `ValueError` and killing the run for every other user in the batch).

Each user is also processed in isolation with its own try/except — one user's bad data
logs a warning and gets skipped instead of aborting the batch for everyone else.

## Testing approach

The scheduler is **disabled during tests** (`SCHEDULER_ENABLED` defaults `False`) — cron
ticks firing mid-run against the test database would make the suite non-deterministic.
Tests call the job functions directly instead. That APScheduler can run a coroutine on a
cron trigger is the library's responsibility, not this project's; what's worth testing is
the job logic.

The scheduler startup path *was* verified manually with `SCHEDULER_ENABLED=true`,
confirming all three jobs register with correct next-run times and shut down cleanly.

`POST /jobs/run/subscriptions` exists as a manual trigger so the behaviour is
demonstrable without waiting for a cron tick or editing the system clock.
`GET /jobs/status` answers "are the jobs actually running, and when do they next fire?"
without needing shell access to read logs.

## A recurring bug, now caught structurally

Three separate features in this project (the WebSocket router, the security router, and
very nearly this one) were fully built — service, schemas, router, tests, frontend — but
never registered with `app.include_router(...)` in `main.py`, making them completely
unreachable. Each time it presented as a confusing runtime failure rather than an obvious
one.

`test_every_router_module_is_registered` now enumerates every module in `app/routers/`
and asserts it appears in `main.py`. It was verified to actually work by temporarily
deleting the `jobs` registration and confirming the test failed. That class of bug can't
recur silently now.

## Known limitation

This is an **in-process** scheduler — same class of constraint as the WebSocket
`ConnectionManager` and the Diary/Vault unlock store. Run two Uvicorn workers and both
fire every job. The jobs are idempotent so the damage is bounded, but a horizontally
scaled deployment should either run the scheduler as a single separate process/container,
or move to Celery Beat with a shared broker.
