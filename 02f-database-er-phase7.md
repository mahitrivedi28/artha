# ARTHA — Phase 7 additions (Reports, Notifications, Subscriptions)

## Reports

`report_data_service.py` gathers data by calling `expense_service`/`income_service`/
`budget_service` — the same functions the dashboard and analytics endpoints use — rather
than re-querying the DB independently. A report can never disagree with the dashboard
about what happened in a given month, because they share the exact same aggregation code.

`report_file_service.py` renders that data three ways:
- **PDF** (ReportLab) — summary table + category breakdown + full transaction list (monthly)
  or a 12-month breakdown table (yearly). Currency is rendered as `Rs. 1,234.56` rather than
  the ₹ glyph — ReportLab's built-in Helvetica font doesn't include it, and substituting
  a custom font just for one glyph wasn't worth the added complexity for this project's scope.
- **Excel** (OpenPyXL) — separate sheets (Summary / Category Breakdown / Transactions, or
  Summary / Monthly Breakdown for yearly), with real numeric cells, not text — so a user can
  immediately sum/chart them in Excel without a to-number conversion step.
- **CSV** — plain `csv` stdlib, no library needed.

`GET /reports/monthly` and `/yearly` return the same underlying data as JSON for an
in-app preview (used by the Reports tab in `settings.html`) before committing to a download.

**Testing note:** the tests don't just check HTTP 200 — they parse the actual generated
files (`pypdf.PdfReader` extracting real text, `openpyxl.load_workbook` reading real cell
values) and assert the seeded transaction amounts and merchant name appear in them. A
bug where PDF/Excel numbers silently diverged from the JSON preview would have been
caught this way; a status-code-only test would have missed it entirely.

## Notifications

The `Notification` model and CRUD service already existed going into this phase, but
nothing was creating rows — it was a working API with nothing feeding it. This phase wires
real creation into three trigger points:
- **Budget alerts**: every time `budget_service.get_budget_overview` is computed for the
  *current* month (not historical browsing), any category at/over its threshold gets a
  notification — deduped so viewing the budget page repeatedly doesn't spam duplicates
  (`notification_service.create_if_new_today`, scoped by exact message match within "today").
- **Security events**: account lockout and password-reset-completed now create a visible
  notification, not just an `AuditLog` row — a user should see "your password changed" in
  their own notification feed, not only in a log they'd have to think to check.
- **Subscription renewals**: a subscription due within 3 days generates a reminder,
  deduped the same way, synced whenever `GET /subscriptions` is called.
- **Goal deadlines**: an active goal due within 7 days generates a reminder, synced
  whenever `GET /goals` is called.

AI-insight notifications (the fifth type the brief lists) are not auto-generated yet —
`AIInsight` rows exist from Phase 5 but nothing currently promotes one to a `Notification`.
Noted as a gap, not silently skipped.

A shared notification bell dropdown (`app.js`) works across every page with the standard
bell icon — no per-page HTML changes needed, since it attaches by finding
`.icon-btn[title="Notifications"]` at load time. `goals.html` is the one page missing the
bell markup entirely (an oversight from when that page was hand-built separately from the
others) — a minor, cosmetic gap, not a functional blocker.

## Subscriptions

Straightforward CRUD, with one calculation worth documenting: `monthly_equivalent()`
normalizes weekly/yearly billing to a comparable monthly figure (`weekly × 52/12`,
`yearly ÷ 12`) so `GET /subscriptions/summary`'s `monthly_total` is a correctly-weighted
sum, not just adding a ₹100/week gym membership and a ₹1200/year plan together as if they
were on the same cadence.
