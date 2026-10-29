# ARTHA — API Design

Base URL: `/api/v1`. Every response uses the envelope below (see `app/utils/responses.py`).

```json
{ "success": true,  "message": "...", "data": {} }
{ "success": false, "message": "...", "error_code": "INVALID_CREDENTIALS" }
```

## Phase 1 — Authentication (built in this delivery)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /auth/register | none | creates user, is_verified=false, sends OTP |
| POST | /auth/verify-otp | none | purpose=email_verification, flips is_verified |
| POST | /auth/resend-otp | none | rate-limited, invalidates previous OTP |
| POST | /auth/login | none | checks lockout, verifies password, issues tokens |
| POST | /auth/refresh | refresh cookie/body | rotates refresh token |
| POST | /auth/logout | access token | revokes refresh token |
| POST | /auth/forgot-password | none | always 200, doesn't leak whether email exists |
| POST | /auth/reset-password | reset token | consumes token, invalidates all refresh tokens |
| GET | /auth/me | access token | current user profile |

### Login flow detail (matches the lockout/attempts UI already in `login.html`)

1. Look up user by email. If not found → generic `401 INVALID_CREDENTIALS` (don't leak
   which field was wrong).
2. If `locked_until` is in the future → `423 ACCOUNT_LOCKED` with `retry_after_seconds`.
3. Verify password with Argon2id. On failure: increment `failed_login_attempts`; if it
   hits 5, set `locked_until = now() + 15min`, write an `audit_logs` row, return
   `423 ACCOUNT_LOCKED`. Otherwise return `401` with `attempts_remaining`.
4. On success: reset `failed_login_attempts` to 0, issue access token (15 min) +
   refresh token (7 days, stored hashed in `refresh_tokens`), write `audit_logs` row.

## Later phases (endpoint list only — implemented when their phase is reached)

Expenses, Income, Budget, Dashboard, Goals, AI, Diary, Vault, Receipts, Reports,
Notifications, Subscriptions, Analytics — full path/verb list exactly as specified in the
project brief. Not repeated here to avoid drift between two documents; the brief itself is
the source of truth for those paths and will be implemented in the stated phase order.

## Error codes used in Phase 1

`VALIDATION_ERROR` (422), `EMAIL_ALREADY_REGISTERED` (409), `INVALID_CREDENTIALS` (401),
`ACCOUNT_LOCKED` (423), `NOT_VERIFIED` (403), `INVALID_OTP` (400), `OTP_EXPIRED` (400),
`OTP_MAX_ATTEMPTS` (429), `INVALID_TOKEN` (401), `TOKEN_EXPIRED` (401), `RATE_LIMITED` (429).
