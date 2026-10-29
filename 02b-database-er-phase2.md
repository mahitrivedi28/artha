# ARTHA — Phase 2 additions to Database ER

Extends `docs/02-database-er.md`. All money columns `NUMERIC(12,2)`.

### categories
| column | type | notes |
|---|---|---|
| id | UUID pk | |
| user_id | UUID fk → users, indexed | categories are per-user (seeded defaults on register) |
| name | varchar(60) | e.g. "Food & Dining" |
| icon | varchar(10) nullable | emoji, matches frontend's `txn-icon` |
| kind | varchar(10) | `expense` \| `income` — same table serves both so Budget (Phase 3) can FK once |
| is_default | boolean default false | seeded categories vs user-created |
| created_at | timestamptz | |

### expenses
| id, user_id fk, category_id fk → categories, amount NUMERIC(12,2), merchant varchar(120), note text nullable, payment_method varchar(20), spent_on date, created_at, updated_at |

`payment_method` is a plain string constrained at the Pydantic layer (`upi` \| `cash` \|
`debit_card` \| `credit_card`) rather than a DB enum — keeps adding a new method a one-line
schema change, not a migration.

### incomes
| id, user_id fk, source varchar(60), amount NUMERIC(12,2), note text nullable, received_on date, created_at, updated_at |

## Indexes added

`ix_expenses_user_spent_on (user_id, spent_on)` — the dashboard's "this month" and
"today" queries filter on exactly this pair, so it's a composite index, not two
separate ones.
`ix_incomes_user_received_on (user_id, received_on)` — same reasoning.
`ix_categories_user_kind (user_id, kind)`.

## Default categories seeded on registration

Food & Dining 🍔, Transport 🚌, Education 📚, Bills 📱, Shopping 🛍️, Health 💊,
Entertainment 🎬, Other 🗂️ (kind=`expense`); Stipend 🎓, Freelance 💼, Tuition 📖,
Family Support 🏠, Other 🗂️ (kind=`income`) — matches the categories already shown as
static options in `expenses.html` / `income.html`.
