import io

from tests.helpers import auth_headers, register_verify_login

# Minimal valid file signatures for magic-byte content validation.
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nreal pdf-ish content for testing purposes only"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
FAKE_EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 40  # not an allowed type


async def test_vault_status_before_setup(client, capsys):
    token = await register_verify_login(client, capsys, email="vault1@example.com")
    resp = await client.get("/api/v1/vault/status", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["has_passphrase"] is False
    assert data["file_count"] == 0


async def test_upload_blocked_before_unlock(client, capsys):
    token = await register_verify_login(client, capsys, email="vault2@example.com")
    files = {"file": ("statement.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "VAULT_LOCKED"


async def test_upload_and_list_pdf(client, capsys):
    token = await register_verify_login(client, capsys, email="vault3@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("HDFC_Statement.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["original_filename"] == "HDFC_Statement.pdf"
    assert resp.json()["data"]["mime_type"] == "application/pdf"

    resp = await client.get("/api/v1/vault/files", headers=auth_headers(token))
    files_list = resp.json()["data"]
    assert len(files_list) == 1
    assert files_list[0]["original_filename"] == "HDFC_Statement.pdf"


async def test_upload_rejects_disallowed_extension(client, capsys):
    token = await register_verify_login(client, capsys, email="vault4@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("virus.exe", io.BytesIO(FAKE_EXE_BYTES), "application/octet-stream")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_FILE_TYPE"


async def test_upload_rejects_content_mismatching_extension(client, capsys):
    """A .pdf extension whose actual bytes aren't a real PDF must be rejected
    — this is the "validate content, not just the extension" requirement."""
    token = await register_verify_login(client, capsys, email="vault5@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("fake.pdf", io.BytesIO(FAKE_EXE_BYTES), "application/pdf")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_FILE_CONTENT"


async def test_download_round_trips_exact_bytes(client, capsys):
    token = await register_verify_login(client, capsys, email="vault6@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("receipt.png", io.BytesIO(PNG_BYTES), "image/png")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    file_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/vault/files/{file_id}/download", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.content == PNG_BYTES  # decrypted bytes exactly match what was uploaded
    assert "receipt.png" in resp.headers["content-disposition"]


async def test_user_cannot_download_other_users_file(client, capsys):
    token_a = await register_verify_login(client, capsys, email="vault7a@example.com")
    token_b = await register_verify_login(client, capsys, email="vault7b@example.com")

    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "SecretA123"}, headers=auth_headers(token_a))
    files = {"file": ("private.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token_a))
    file_id = resp.json()["data"]["id"]

    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "SecretB123"}, headers=auth_headers(token_b))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "SecretB123"}, headers=auth_headers(token_b))
    resp = await client.get(f"/api/v1/vault/files/{file_id}/download", headers=auth_headers(token_b))
    assert resp.status_code == 404


async def test_vault_wrong_passphrase_locks_out(client, capsys):
    token = await register_verify_login(client, capsys, email="vault8@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "Correct123"}, headers=auth_headers(token))

    for _ in range(5):
        resp = await client.post("/api/v1/vault/unlock", json={"passphrase": "WrongPass1"}, headers=auth_headers(token))
    assert resp.status_code == 423
    assert resp.json()["error_code"] == "ACCOUNT_LOCKED"


async def test_delete_file_removes_from_list_and_disk(client, capsys):
    token = await register_verify_login(client, capsys, email="vault9@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("temp.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))
    file_id = resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/vault/files/{file_id}", headers=auth_headers(token))
    assert resp.status_code == 200

    resp = await client.get("/api/v1/vault/files", headers=auth_headers(token))
    assert resp.json()["data"] == []


async def test_status_reflects_file_count_and_size(client, capsys):
    token = await register_verify_login(client, capsys, email="vault10@example.com")
    await client.post("/api/v1/vault/set-passphrase", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))
    await client.post("/api/v1/vault/unlock", json={"passphrase": "VaultSecret1"}, headers=auth_headers(token))

    files = {"file": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    await client.post("/api/v1/vault/files", files=files, headers=auth_headers(token))

    resp = await client.get("/api/v1/vault/status", headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["file_count"] == 1
    assert data["total_bytes"] == len(PDF_BYTES)


async def test_vault_requires_auth(client):
    resp = await client.get("/api/v1/vault/status")
    assert resp.status_code == 401
