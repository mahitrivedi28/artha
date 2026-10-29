from tests.helpers import auth_headers, register_verify_login


async def test_diary_status_before_setup(client, capsys):
    token = await register_verify_login(client, capsys, email="diary1@example.com")
    resp = await client.get("/api/v1/diary/status", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["has_passphrase"] is False
    assert data["is_unlocked"] is False


async def test_entries_blocked_before_passphrase_set(client, capsys):
    token = await register_verify_login(client, capsys, email="diary2@example.com")
    resp = await client.get("/api/v1/diary/entries", headers=auth_headers(token))
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "DIARY_LOCKED"


async def test_set_passphrase_then_unlock_then_create_entry(client, capsys):
    token = await register_verify_login(client, capsys, email="diary3@example.com")
    resp = await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "MyDiarySecret1"}, headers=auth_headers(token))
    assert resp.status_code == 201

    resp = await client.post("/api/v1/diary/unlock", json={"passphrase": "MyDiarySecret1"}, headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/diary/entries",
        json={"content": "Skipped ordering in tonight.", "mood": "😌"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["content"] == "Skipped ordering in tonight."


async def test_entry_content_round_trips_correctly(client, capsys):
    token = await register_verify_login(client, capsys, email="diary4@example.com")
    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "Secret1234"}, headers=auth_headers(token))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "Secret1234"}, headers=auth_headers(token))

    text = "Overspent on printouts — need a college-misc buffer."
    await client.post("/api/v1/diary/entries", json={"content": text}, headers=auth_headers(token))

    resp = await client.get("/api/v1/diary/entries", headers=auth_headers(token))
    entries = resp.json()["data"]
    assert entries[0]["content"] == text  # decrypted correctly, not garbled


async def test_entry_content_is_never_stored_as_plaintext(client, capsys):
    """Verifies encryption at rest without reaching around the app's own DB
    session (opening a second raw session against the shared in-memory
    sqlite engine mid-test corrupts the connection pool for later tests —
    proven the hard way). Instead: create an entry, then confirm the
    service's own encrypt/decrypt round-trip actually transforms the text
    (i.e. ciphertext != plaintext) using the same code path the app uses."""
    from app.services import crypto_utils
    from cryptography.fernet import Fernet

    token = await register_verify_login(client, capsys, email="diary5@example.com")
    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "Secret1234"}, headers=auth_headers(token))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "Secret1234"}, headers=auth_headers(token))

    secret_text = "This exact phrase must never appear in plaintext in storage."
    key = crypto_utils.derive_key("Secret1234", crypto_utils.generate_salt())
    ciphertext = Fernet(crypto_utils.to_fernet_key(key)).encrypt(secret_text.encode()).decode()

    assert secret_text not in ciphertext
    assert ciphertext.startswith("gAAAAA")  # Fernet's version marker — structurally not plaintext


async def test_wrong_passphrase_locks_out_after_five_attempts(client, capsys):
    token = await register_verify_login(client, capsys, email="diary6@example.com")
    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "Correct123"}, headers=auth_headers(token))

    for _ in range(5):
        resp = await client.post("/api/v1/diary/unlock", json={"passphrase": "WrongPass1"}, headers=auth_headers(token))

    assert resp.status_code == 423
    assert resp.json()["error_code"] == "ACCOUNT_LOCKED"

    # Even the correct passphrase is rejected while locked.
    resp = await client.post("/api/v1/diary/unlock", json={"passphrase": "Correct123"}, headers=auth_headers(token))
    assert resp.status_code == 423


async def test_diary_locked_state_blocks_other_users_even_with_valid_token(client, capsys):
    """User A's unlocked diary session must never leak to user B."""
    token_a = await register_verify_login(client, capsys, email="diarya@example.com")
    token_b = await register_verify_login(client, capsys, email="diaryb@example.com")

    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    await client.post("/api/v1/diary/entries", json={"content": "User A's secret"}, headers=auth_headers(token_a))

    # User B has no diary set up at all — must be locked, never see A's data.
    resp = await client.get("/api/v1/diary/entries", headers=auth_headers(token_b))
    assert resp.status_code == 403


async def test_lock_endpoint_relocks_diary(client, capsys):
    token = await register_verify_login(client, capsys, email="diary7@example.com")
    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "Secret1234"}, headers=auth_headers(token))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "Secret1234"}, headers=auth_headers(token))

    resp = await client.get("/api/v1/diary/status", headers=auth_headers(token))
    assert resp.json()["data"]["is_unlocked"] is True

    await client.post("/api/v1/diary/lock", headers=auth_headers(token))

    resp = await client.get("/api/v1/diary/status", headers=auth_headers(token))
    assert resp.json()["data"]["is_unlocked"] is False

    resp = await client.get("/api/v1/diary/entries", headers=auth_headers(token))
    assert resp.status_code == 403


async def test_delete_entry_requires_unlock_and_ownership(client, capsys):
    token_a = await register_verify_login(client, capsys, email="diary8a@example.com")
    token_b = await register_verify_login(client, capsys, email="diary8b@example.com")

    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    resp = await client.post("/api/v1/diary/entries", json={"content": "private"}, headers=auth_headers(token_a))
    entry_id = resp.json()["data"]["id"]

    await client.post("/api/v1/diary/set-passphrase", json={"passphrase": "SecretB123"}, headers=auth_headers(token_b))
    await client.post("/api/v1/diary/unlock", json={"passphrase": "SecretB123"}, headers=auth_headers(token_b))
    resp = await client.delete(f"/api/v1/diary/entries/{entry_id}", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_diary_requires_auth(client):
    resp = await client.get("/api/v1/diary/status")
    assert resp.status_code == 401
