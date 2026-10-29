# ARTHA — Architecture

## Layers

```
frontend/*.html + frontend/js/*.js   (presentation only)
        │  fetch() via frontend/js/api.js
        ▼
FastAPI routers        backend/app/routers/*.py
        │  (auth dependency resolves current_user from JWT)
        ▼
Service layer           backend/app/services/*.py     ← ALL business logic lives here
        │
        ▼
SQLAlchemy 2.x models   backend/app/models/*.py
        │
        ▼
PostgreSQL
```

**Rule enforced throughout:** routers only parse/validate input (via Pydantic schemas) and
call a service function. Routers never contain calculations, SQL, or security decisions.
Services never touch `Request`/`Response` objects — they're plain Python, which is what
makes them unit-testable with Pytest without spinning up FastAPI.

## Request lifecycle (example: `POST /api/v1/expenses`)

1. JS `api.js → createExpense()` sends `fetch` with `Authorization: Bearer <access_token>`.
2. `dependencies.get_current_user` decodes the JWT, loads the `User` row. If invalid/expired → 401.
3. Router `expenses.py` validates body against `ExpenseCreate` Pydantic schema.
4. Router calls `expense_service.create_expense(db, user_id=current_user.id, data=...)`.
   `user_id` **always** comes from the JWT, never from the request body — this is the
   single most important rule in the whole backend (prevents User A editing User B's data).
5. Service writes via SQLAlchemy, returns ORM object.
6. Router serializes with `ExpenseOut` schema, wraps in the standard envelope, returns.

## AI layer

`app/ai/gemini_client.py` is the *only* file that imports the Gemini SDK. Services build a
constrained prompt (system instructions + the user's real numbers pulled from Postgres) and
call this client. The client never receives raw user input without the service layer
having first fetched/verified the underlying data — this is what "Do not allow AI to invent
financial data" means in practice: Python computes the numbers, AI only explains them.

## OCR layer

`app/services/ocr_service.py` wraps EasyOCR/Tesseract, returns structured fields. The
`/api/v1/receipts/scan` endpoint returns this as a **draft** — nothing is written to the
`Expense` table until the user confirms via a normal `POST /api/v1/expenses` call.

## Why FastAPI + PostgreSQL

- FastAPI gives Pydantic v2 validation "for free" at the API boundary, plus auto-generated
  `/docs` (Swagger), which matters for a diploma project you'll be asked to demo/explain.
- PostgreSQL gives real transactional integrity for money data (SQLite is fine for a demo
  but doesn't enforce the same constraints under concurrent writes) and native support for
  the numeric/decimal types you want for currency (never floats for money).

## Deployment shape (Phase 8, not built yet)

`docker-compose.yml` runs two services: `db` (postgres:16) and `api` (this FastAPI app via
Uvicorn). `.env` supplies `DATABASE_URL`, `JWT_SECRET`, `GEMINI_API_KEY` — never committed.
