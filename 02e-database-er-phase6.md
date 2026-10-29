# ARTHA — Phase 6 additions (Diary, Vault)

## Design principle shared by both

A Diary/Vault passphrase is **not** the account login password — compromising one must
never compromise the other. Neither passphrase is ever stored: only an Argon2id hash
(verification) and a random salt (re-deriving the encryption key on correct entry) live
in the `users` table. See `app/services/crypto_utils.py`.

Unlocking derives a symmetric key server-side and holds it in
`app/services/unlock_session_store.py` — an in-memory, per-process, TTL'd store. The key
**never** reaches the client and is never written to the database. This is a documented
scope limitation: a multi-worker production deployment would need this backed by Redis
instead of process memory; single-process Uvicorn (this project's actual deployment
target) is correct as-is.

## Diary

- `diary_entries.encrypted_content` — Fernet ciphertext, decrypted only for the duration
  of a request, only while the caller's unlock session is valid.
- Lockout mirrors login exactly: 5 wrong passphrases → 15 minutes locked
  (`diary_failed_attempts` / `diary_locked_until` on `users`).
- Every diary endpoint except `/status` and `/set-passphrase` requires an active unlock
  session — enforced in `diary_service._require_unlocked`, not by trusting a client flag.

## Vault

- File content: **AES-256-GCM** (authenticated encryption — tampering with the ciphertext
  on disk is detected on decrypt, not silently accepted), a fresh random nonce per file.
- Filenames: encrypted separately with Fernet, so a directory listing of `vault_storage/`
  reveals nothing — files live on disk under a random UUID with no extension.
- Upload validation is three layers deep: extension allowlist, declared size ≤ 10MB, **and**
  magic-byte content sniffing (`_sniff_mime`) — a `.pdf` that isn't actually PDF bytes is
  rejected with `INVALID_FILE_CONTENT`, not trusted on the extension alone.
- `GET /vault/files/{id}/download` streams decrypted bytes directly in the response; nothing
  decrypted ever touches disk.

## Receipt OCR

`app/services/ocr_service.py`. Two-layer approach:
1. **Tesseract** (real local binary, no network/API key needed) extracts raw text.
2. A deterministic regex parser (`heuristic_parse`) turns that into `merchant`/`amount`/
   `date`/`gst`/`items`. This is the layer that runs with zero configuration.
3. **If** `GEMINI_API_KEY` is set, its structured extraction *replaces* the heuristic
   result (better accuracy on messy real-world receipts) — but the heuristic parser is
   always computed first and is the fallback the moment Gemini is unavailable or fails.

`POST /api/v1/receipts/scan` never writes to `expenses` — it returns a draft only. The
frontend's "Scan a receipt" button (in the Add Expense modal on `expenses.html`)
pre-fills the form fields and requires the user to review and click Save, matching the
brief's "User must confirm before creating an expense."

**Testing note, different from the AI tests:** `tests/test_receipts.py` does *not* mock
Tesseract — it's a real local binary with no network dependency, so the tests render a
synthetic receipt image with PIL and run it through the actual OCR pipeline. Only the
optional Gemini refinement step is mocked (same reasoning as `test_ai.py`).

## Diary testing note

One test-writing lesson worth recording: an early version of a diary test opened a second
raw SQLAlchemy session directly against the shared in-memory SQLite test engine (bypassing
the app's own DB dependency injection) to inspect a row. This corrupted the connection pool
for every subsequent test in the file (`no such table: users` on unrelated tests). Fixed by
never reaching around the app's session handling in a test — verify behavior through the API
and the same code paths the app itself uses, not through a side-channel into the DB.
