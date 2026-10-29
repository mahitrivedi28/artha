# ARTHA — Security Plan

## Identity & authorization
- JWT access tokens (15 min) signed with `JWT_SECRET` (HS256), refresh tokens (7 days)
  stored **hashed** in `refresh_tokens`, rotated on every use, revocable on logout.
- `get_current_user` dependency is the only place a router learns "who is this". Every
  service function takes `user_id` from this dependency — request bodies are never trusted
  for identity. This is what stops User A reading/editing User B's rows even if they forge
  a request with someone else's ID in the payload.
- Every later-phase query filters by `WHERE user_id = :current_user_id` at the ORM level,
  not just at the router level, so a missed check in one router can't leak data.

## Passwords & OTP
- Argon2id (via `passlib` / `argon2-cffi`) for password hashing — memory-hard, resistant to
  GPU cracking, the current OWASP recommendation over bcrypt for new projects.
- OTP codes are hashed (SHA-256 is fine here — codes are short-lived and rate-limited, unlike
  passwords) before storage, so a DB read alone doesn't leak valid codes.
- Account lockout: 5 failed attempts → 15 minute lock, enforced in `auth_service.py`, not JS.
- OTP: 6 digits, 5 minute expiry, max 5 verify attempts, then must resend.

## Transport & session
- CORS restricted to the known frontend origin(s) via `.env`, not `*`.
- Refresh token delivered as `HttpOnly`, `Secure` (in production), `SameSite=Lax` cookie —
  unreachable from JS, mitigating token theft via XSS.
- Rate limiting on `/auth/login`, `/auth/register`, `/auth/resend-otp`,
  `/auth/forgot-password` independent of the per-account lockout (protects against
  distributed attempts across many accounts / email enumeration).

## Data protection (later phases, planned now so schema doesn't need rework)
- Vault files: AES-256-GCM, random filename on disk, original name stored encrypted in DB,
  key derived from a server-side secret + per-user salt — never from something guessable.
- Diary: passphrase hashed separately from the login password; unlock issues a short-lived
  server-side session flag (not a client-derivable key), expires in 15 minutes, enforced by
  checking a timestamp server-side on every diary request — not a JS timer.

## Application hardening
- All input validated by Pydantic v2 schemas (`extra="forbid"` so unexpected fields 422
  instead of being silently accepted).
- SQLAlchemy ORM only — no raw string-interpolated SQL, eliminates SQL injection surface.
- Secrets (`JWT_SECRET`, `GEMINI_API_KEY`, `DATABASE_URL`) only via environment variables,
  `.env` is gitignored, `.env.example` documents required keys with placeholder values.
- `AuditLog` rows written for security-relevant events, surfaced back to the user via the
  "Recent account activity" panel already in `settings.html` — security state is visible to
  the account owner, not just to admins.

## What Phase 1 does NOT cover yet (explicitly deferred, not forgotten)
File upload validation (Phase 6 — Vault), AI prompt-injection containment (Phase 5),
receipt OCR input sanitization (Phase 6). Each gets its own security review when built,
rather than being bolted on generically now.
