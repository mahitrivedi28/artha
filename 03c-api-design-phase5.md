# ARTHA — Phase 5 additions to API design

Extends `docs/03-api-design.md`.

## Financial Health Score

| Method | Path | Notes |
|---|---|---|
| GET | /health-score | Zero AI involvement — pure Python arithmetic over real rows (see `docs/05-security-plan.md` note on this being a hard project requirement) |

## AI (Gemini)

| Method | Path | Notes |
|---|---|---|
| POST | /ai/goal-plan | Body: `{goal_id}`. Every number in the response's `based_on` field is the same number `goals/{id}/analysis` would return — the AI explains it, doesn't recompute it |
| POST | /ai/chat | Body: `{message}`. Context sent to the model is built entirely from the authenticated user's own dashboard/goals data — never user-suppliable |
| GET | /ai/chat/history | Last 20 messages, both roles |
| POST | /ai/categorize-expense | Body: `{merchant, note}`. Suggested category is validated against the user's real category list — an AI suggestion that doesn't match a real category returns `matched_category_id: null` rather than fabricating one |

All four return `503 AI_UNAVAILABLE` if `GEMINI_API_KEY` isn't set or the Gemini call
fails — this is a deliberate, tested failure mode, not an unhandled exception. The rest
of ARTHA has zero dependency on AI being configured.

## Testing note

This sandbox has no network route to Google's API and no real API key. Tests in
`tests/test_ai.py` mock `app.ai.gemini_client` — the standard, correct way to unit-test
an external LLM integration regardless of environment (no network flakiness, no API
cost, deterministic assertions). What's verified for real: prompt construction pulls
actual DB numbers (not placeholders), response parsing/validation, cross-user data
isolation, and the `AI_UNAVAILABLE` failure path. Before a real deployment, a small
number of live-Gemini smoke tests (not part of the main suite, run manually with a
real key) would be worth adding to catch prompt/response-shape drift.
