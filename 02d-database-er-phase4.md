# ARTHA — Phase 4 additions (Goal-Based Savings Planner)

## Database

### goals
| column | type | notes |
|---|---|---|
| id | UUID pk | |
| user_id | UUID fk → users, indexed | |
| title | varchar(120) | |
| icon | varchar(8), default 🎯 | emoji, matches the card UI |
| target_amount | NUMERIC(12,2) | |
| deadline | date | must be strictly in the future at creation (Pydantic validator) |
| status | varchar(20), default `active` | `active` \| `completed` \| `abandoned` |
| created_at / updated_at | timestamptz | |

### goal_contributions
| id, goal_id fk → goals (cascade delete), user_id fk → users, amount NUMERIC(12,2), note varchar(300) nullable, contributed_on date, created_at |

**Design choice:** `current_savings` is not a stored column on `goals` — it's always
`sum(goal_contributions.amount)`, computed fresh on every read. This trades a small amount
of query cost for the guarantee that the number can never drift out of sync with its own
ledger, which matters more for money than it does for e.g. a view count.

## API

| Method | Path | Notes |
|---|---|---|
| POST | /goals | `deadline` in the past → `422` |
| GET | /goals | Ordered by deadline (soonest first) |
| GET/PUT/DELETE | /goals/{id} | Owner-only, `404` (not `403`) for someone else's goal |
| POST | /goals/{id}/contribute | Auto-flips `status` to `completed` if the contribution meets or exceeds the target |
| GET | /goals/{id}/contributions | Full ledger, oldest first |
| GET | /goals/{id}/analysis | The actual planner math — see below |

## The planner math (`goal_service.analyze_goal`)

Per the brief: *"Do NOT ask AI to perform basic arithmetic. Python must calculate
financial numbers accurately."* Every field below is deterministic Python, unit-tested
directly (`tests/test_goals.py::test_goal_analysis_math` asserts `required_daily_saving ==
remaining / days_remaining` to the cent):

- `days_remaining` / `weeks_remaining` / `months_remaining` (months uses a 30.44-day
  average, not a hardcoded 30 — small but correct)
- `required_daily/weekly/monthly_saving` = `remaining_amount` divided across each remaining
  unit — floors at 0 if already funded, and if the deadline has already passed the entire
  remaining amount is reported as due immediately rather than dividing by zero or negative days
- `average_monthly_contribution` = total saved so far ÷ whole months elapsed since the goal
  was created (minimum 1 month, so a same-day contribution doesn't produce an inflated rate)
- `projected_completion_date` = today + (remaining ÷ average_monthly_contribution) months,
  or `null` if there's no contribution history yet to project from
- `on_track` = projected completion falls on or before the deadline (always `true` once
  `remaining_amount` hits zero)

This function is also the only thing Phase 5's AI Goal Planner is allowed to read from —
the AI explains `required_monthly_saving`, it never recalculates it (see
`docs/03c-api-design-phase5.md`).
