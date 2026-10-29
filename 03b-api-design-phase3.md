# ARTHA — Phase 3 additions to API design

Extends `docs/03-api-design.md`.

## Budgets

| Method | Path | Notes |
|---|---|---|
| GET | /budgets?month=&year= | Returns `BudgetOverview`: per-category budgets (spent/remaining/%/status) + `alerts` for any category ≥ its threshold |
| POST | /budgets | Upsert — same user+category+month+year updates the existing row instead of duplicating (`uq_budget_user_category_period`) |
| DELETE | /budgets/{id} | Owner-only, 404 (not 403) for someone else's budget |

Budgets can only be set on `expense`-type categories (`422 INVALID_CATEGORY_TYPE` otherwise)
— setting a "budget" on an income category is a modeling error, not a valid use case.

`status` is derived, not stored: `on_track` / `warning` (≥ `alert_threshold`) / `exceeded`
(≥ 100%) — computed fresh on every read from real expense totals, so it's never stale the
way a periodically-recalculated cached field would be.

## Dashboard (updated)

`remaining_budget` and `budget_alerts` — placeholder fields since Phase 1 — are now populated
from the same budget overview logic. No separate code path: the dashboard alert banner and
the Budget page's alert list are backed by the identical `budget_service.get_budget_overview`
call, so they can never disagree with each other.

## Analytics

| Method | Path | Notes |
|---|---|---|
| GET | /analytics/monthly?year= | Always 12 points (Jan–Dec), zero-filled — a chart never has gaps |
| GET | /analytics/yearly | Only years with at least one transaction — years are open-ended, unlike months |
| GET | /analytics/category?date_from=&date_to= | Arbitrary range, not locked to a calendar month like the dashboard's category breakdown |
| GET | /analytics/income-vs-expense?months= | Reuses the exact trend functions already backing the dashboard chart |
| GET | /analytics/savings?months= | income − expense per month |
| GET | /analytics/spending-trend?days= | Daily granularity, zero-filled — for a future heatmap view |
