# ARTHA — Account security features (2FA, sessions, audit log)

Added after the initial 8 phases, alongside real email delivery and WebSockets.

## TOTP two-factor authentication

Standard RFC 6238 TOTP (`pyotp`) — works with Google Authenticator, Authy, 1Password, or
any other authenticator app. Chosen over the email-OTP-only approach the original UI
mocked up because email 2FA is only as strong as the email account behind it; a TOTP
secret lives on a device the user physically holds.

**The secret is encrypted at rest**, not stored in plaintext — `totp_service.py` wraps it
with Fernet using a server-side key (`APP_ENCRYPTION_KEY`). A database dump alone
therefore doesn't hand an attacker the ability to generate valid codes. The key is
deliberately separate from `JWT_SECRET`: they do different jobs (session signing vs.
secret-at-rest encryption), and rotating one shouldn't silently break the other. For
zero-config local dev the service derives a fallback key from `JWT_SECRET`, but a real
deployment must set `APP_ENCRYPTION_KEY` explicitly.

**Two-phase enable**: `POST /security/2fa/setup` generates a secret and QR code but
stores it as a *pending* secret only. 2FA isn't actually switched on until
`POST /security/2fa/confirm` receives a valid code from the user's app. This prevents the
failure mode where someone scans a QR, misconfigures their app, and locks themselves out
of an account that now demands codes they can't produce.

**Backup codes**: eight single-use codes issued on enable, stored as hashes (never
plaintext), regenerable with password confirmation. Disabling 2FA also requires the
account password — possession of an unlocked session alone isn't enough to strip a
security control off the account.

## Session management

`GET /security/sessions` lists every active (non-revoked, non-expired) refresh token with
its IP, user agent, and creation time, flagging which one is the caller's current
session. Individual sessions can be revoked, or all-but-current in one call.

**A real bug this surfaced**: the "is this the current session" check needs the refresh
token cookie, which was scoped to `path=/api/v1/auth` and therefore never sent to
`/api/v1/security/*`. Widened to `/api/v1`, since both routers sit in the same trust
boundary and already require the same JWT.

**A much bigger bug it surfaced**: `_set_refresh_cookie()` was writing to FastAPI's
injected `response: Response` placeholder, but `login`/`refresh`/`logout` all return
their own `JSONResponse` built by `success()` — so the placeholder (and its cookie) was
silently discarded on every single request. **The refresh-token cookie had never worked
since Phase 1.** Silent session renewal was broken in any real browser for the entire
project; it only went unnoticed because the test suite passes `refresh_token` explicitly
in the request body, which is the documented fallback path. Fixed by setting the cookie
on the response object actually returned. Worth recording as the clearest example in this
project of a bug that a green test suite can hide when tests exercise the fallback path
rather than the primary one.

## Authenticated password change

`POST /auth/change-password` (distinct from the emailed-token reset flow) verifies the
current password, then revokes every *other* session while keeping the caller signed in.
That asymmetry is deliberate: a full reset logs out everywhere because identity was
proven out-of-band and there's no "current session" to preserve; here there is one, and
signing the user out of the device they're actively using would be hostile.

## Audit log UI

The `AuditLog` table has existed since Phase 1 and was already being written to by auth,
diary, and vault flows — but was never readable by the user it described.
`GET /security/audit-log` exposes each user's own entries (and strictly only their own,
tested directly), rendered as a timeline in Settings → Security.

## Frontend

Settings → Security is now entirely real, replacing UI that previously called
`showToast('Password updated')` with no backend request behind it: working password
change with strength meter, QR-code 2FA setup with confirmation and one-time backup code
reveal, live session list with per-session revoke, and the audit log timeline.
