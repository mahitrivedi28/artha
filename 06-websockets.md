# ARTHA — Real-time layer (WebSockets)

Added after the initial 8 phases. Every REST endpoint still works exactly as before —
this is a pure addition, not a replacement for anything.

## Why this exists

Before this, a second open tab (or a second device) never found out about a new
expense, a budget alert, or an account lockout until it was manually refreshed. That's
fine for a coursework demo but doesn't feel like a real product. `GET /dashboard`,
`GET /expenses`, etc. are all still the source of truth — the WebSocket layer only tells
an already-open page *when* to re-fetch, it never replaces a REST call with pushed data.

## Auth: token as a query param, not a ticket system

Browsers can't attach an `Authorization` header to a WebSocket handshake. The standard
workaround — and what's used here — is passing the access token as a query param:
`wss://.../api/v1/ws?token=<access_token>`. It's validated exactly like a normal
request (same `decode_access_token`, same "user must exist and be active" check).

This does mean the access token can end up in server access logs, which a longer-lived
token would make a real concern. It's an acceptable tradeoff here specifically *because*
access tokens are short-lived (15 minutes, same as every other endpoint) — by the time a
log line could plausibly be read by anyone, the token in it is very likely already
expired. A production system handling more sensitive data might instead issue a
short-lived, single-use "WS ticket" via an authenticated REST call first, and connect
with that ticket instead of the real access token — noted here as the next hardening
step, not implemented, since it adds a second moving part for marginal benefit at this
project's actual risk level.

## Architecture

```
app/services/ws_manager.py   — in-memory ConnectionManager: user_id -> [open sockets]
app/routers/ws.py            — the /ws route: validates token, registers/unregisters
                                the connection, does nothing else
```

Any service that wants to push a real-time event calls
`ws_manager.manager.send_to_user(user_id, event_type, data)`. Currently wired into:
- `notification_service.create_notification` — every notification (budget alert,
  security event, goal/subscription reminder) is pushed live, not just written to the DB.
- `expense_service.create_expense` / `income_service.create_income` — a `"transaction"`
  event on every new expense/income, so an open dashboard/expenses/income tab can
  refresh itself.

**Known limitation, documented rather than hidden**: `ConnectionManager` is
process-local, in-memory state — same limitation as `unlock_session_store.py` for
Diary/Vault. In a horizontally-scaled deployment (multiple Uvicorn workers/instances), a
user connected to worker A won't receive an event triggered by a request handled on
worker B. A real scaled deployment would back this with Redis pub/sub instead. For this
project's actual deployment target (single Uvicorn process, see `docker-compose.yml`),
it's correct as-is.

## Frontend

`frontend/js/app.js`'s `connectLiveUpdates()` is called from `requireAuth()` — every
page that already requires a session gets a live connection automatically, no per-page
wiring needed. Exponential backoff reconnect (1s/4s/9s, then gives up quietly) means a
dropped connection degrades to "this tab just won't live-update anymore," never an
error the user sees — normal page loads/refreshes still show everything correctly
regardless of WebSocket state.

`handleLiveEvent()` doesn't push data directly into the DOM — it looks for whichever
`load*` function the current page already defines (`loadDashboard`, `loadExpenses`,
`loadIncomePage`) and calls it, reusing each page's existing REST-based rendering path
rather than duplicating render logic for a second, WebSocket-driven code path.

## Testing note

Two testing strategies deliberately used together in `tests/test_websocket.py`:
1. Unit tests against `ConnectionManager` directly with a fake WebSocket object — fast,
   no real network, tests broadcast/prune logic in isolation.
2. Real end-to-end tests using `starlette.testclient.TestClient`, which performs an
   actual WebSocket handshake against the real ASGI app — nothing mocked. These
   deliberately keep HTTP setup calls (`client.post(...)`) and the WebSocket connection
   on the *same* `TestClient` instance rather than mixing with the async httpx fixture
   used elsewhere in the test suite, specifically to avoid a cross-event-loop hazard
   (`TestClient` runs the app in its own managed thread/loop).

**A real bug this caught**: the WebSocket router (`app/routers/ws.py`) was fully built —
connection manager, auth, broadcast hooks, frontend client — but never registered with
`app.include_router(ws.router, ...)` in `main.py`. The route simply didn't exist, so
every connection attempt failed at the handshake with a clean close (code 1000, no
reason) before the handler ever ran. Diagnosed by adding temporary debug prints inside
the handler body, none of which fired — proving the failure was happening before the
handler was even invoked, which pointed straight at routing rather than auth or DB logic.
