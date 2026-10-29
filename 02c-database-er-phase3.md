# ARTHA — Phase 3 additions (Budgets, Analytics)

## Database

### budgets
| column | type | notes |
|---|---|---|
| id | UUID pk | |
| user_id | UUID fk → users, indexed | |
| category_id | UUID fk → categories, indexed | must be an `expense`-type category, enforced in service |
| monthly_limit | NUMERIC(12,2) | |
| month | int (1-12) | |
| year | int | |
| alert_threshold | int, default 80 | percent — matches the `%` shown in `budget.html`'s "Alert threshold" select |
| created_at / updated_at | timestamptz | |

Unique constraint `(user_id, category_id, month, year)` — one budget per category per
month, so "set budget" is naturally an upsert rather than needing separate create/update
UX. Enforced at the DB level, not just the service, so a race between two tabs can't
create duplicates.

## Design decision: alerts are computed, not stored

The original brief says "Create alerts at 75/80/90/100%." Phase 3 computes these
on read (in `budget_service.list_budgets`) rather than writing persistent alert rows —
a `Notification`/alert-history table belongs to Phase 7 (Notifications), where it can be
shared with goal reminders, security events, etc. instead of building a one-off table now
that Phase 7 would have to reconcile with. `budget.html`'s "Budget alert history" panel is
therefore fed from the *current* over-threshold budgets each time the page loads, not a
persisted log — accurate, just not historical yet.

## budgets status field

Computed per budget from `spent = SUM(expenses.amount WHERE category_id=... AND
user_id=... AND month/year match)`:

| percentage_used | status |
|---|---|
| < alert_threshold | `on_track` |
| ≥ alert_threshold and < 100 | `warning` |
| ≥ 100 | `exceeded` |

`GET /dashboard`'s `budget_alerts` is now populated: every budget with status
`warning` or `exceeded` for the current month, as `{category_name, percentage_used,
status, message}`.

## Analytics endpoints (Python computes every number; no AI involved here)

| Method | Path | Returns |
|---|---|---|
| GET | /analytics/monthly?year=YYYY | 12 buckets: income, expense, savings per month |
| GET | /analytics/yearly | one bucket per year that has any data |
| GET | /analytics/category?date_from=&date_to= | expense category breakdown for an arbitrary range (generalizes the dashboard's "this month only" breakdown) |
| GET | /analytics/income-vs-expense?months=N | last N months, both series — same shape the dashboard line chart already consumes |
| GET | /analytics/savings?months=N | last N months' savings (income − expense) |
| GET | /analytics/spending-trend?days=N | daily expense totals for the last N days — finer granularity than the monthly views, for a "spending heatmap"-style chart later |

All of these reuse the same aggregation pattern already established in
`expense_service`/`income_service` (Phase 2) rather than introducing a new querying style.
