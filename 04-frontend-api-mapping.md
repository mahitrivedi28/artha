# ARTHA — Frontend-to-API Mapping (Phase 1)

The existing frontend was built as a static demo — buttons called `showToast()` and JS
comparisons like `if (pw === 'demo1234')`. Phase 1 replaces exactly those demo hooks with
real `fetch` calls through `frontend/js/api.js`. No HTML structure, CSS, or layout changes.

| Page | Old (demo) behaviour | New behaviour |
|---|---|---|
| `login.html` | `handleLoginDemo()` compared password to `'demo1234'` in JS, `simulateLoginAttempt()` faked lockout client-side | Calls `api.loginUser(email, password)`. Real 401/423 responses drive the same `simulateLoginAttempt()` UI (attempt dots, lockout timer) — the *visual* logic is kept, only the *decision* now comes from the server |
| `register.html` | Redirected straight to `otp-verification.html` | Calls `api.registerUser(...)`, then redirects to OTP page only on success |
| `otp-verification.html` | Redirected to `reset-password.html` on click, fake resend countdown | Calls `api.verifyOtp(email, code)`; resend button calls `api.resendOtp(email)` — the countdown UI (`initResendTimer`) is unchanged, it just gets triggered by a real API call now |
| `forgot-password.html` | Redirected to OTP page | Calls `api.forgotPassword(email)` |
| `reset-password.html` | Redirected to success page | Calls `api.resetPassword(token, newPassword)` |
| `dashboard.html`, `expenses.html`, etc. | Hardcoded sample numbers in the HTML | **Not touched in Phase 1.** Wired in Phase 2 (`getDashboard()`, `getExpenses()`) once those endpoints exist — brief explicitly phases this |

## `frontend/js/api.js` contract

```js
const API_BASE_URL = window.ARTHA_API_BASE_URL || 'http://localhost:8000/api/v1';

async function apiRequest(path, { method = 'GET', body, auth = true } = {}) { ... }

// Phase 1
async function registerUser({ fullName, email, password }) { ... }
async function loginUser(email, password) { ... }       // returns { accessToken, refreshToken, user }
async function logoutUser() { ... }
async function verifyOtp(email, code, purpose) { ... }
async function resendOtp(email, purpose) { ... }
async function forgotPassword(email) { ... }
async function resetPassword(token, newPassword) { ... }
async function getCurrentUser() { ... }

// stubs added now, implemented Phase 2+ so later phases only fill function bodies
async function getDashboard() { throw new Error('Not implemented until Phase 2'); }
async function getExpenses(params) { throw new Error('Not implemented until Phase 2'); }
// ...
```

Tokens: access token kept in memory (a module-level variable in `api.js`, not
`localStorage`) plus refresh token in an `HttpOnly` cookie set by the backend — this is why
`/auth/refresh` doesn't take the token in the JSON body in the real implementation, the
browser sends the cookie automatically. `sessionStorage`/`localStorage` are avoided for
tokens specifically because they're readable by any injected script (XSS risk); this is
also why the demo-artifact rule against browser storage lines up with real security practice
here, not just a platform limitation.
