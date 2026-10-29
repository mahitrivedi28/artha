"""
Unlike tests/test_ai.py, these tests do NOT mock the OCR engine — Tesseract
is a real local binary (no network call, no API key), so we can and should
test it for real: render a synthetic receipt image with PIL, run it through
the actual `pytesseract` pipeline, and assert on the extracted fields.
Assertions are written to tolerate minor OCR imprecision (checking for
presence/substring rather than pixel-perfect text) since OCR is never 100%
deterministic even on clean synthetic input.

The Gemini refinement step IS mocked here (same reasoning as test_ai.py) —
this file focuses on proving the Tesseract + heuristic-parser path works,
since that's the path that runs with zero configuration.
"""
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from tests.helpers import auth_headers, register_verify_login

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _render_receipt(lines: list[str]) -> bytes:
    font = ImageFont.truetype(FONT_PATH, 22)
    width, line_height = 500, 32
    height = 40 + line_height * len(lines)
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black", font=font)
        y += line_height
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


SAMPLE_RECEIPT_LINES = [
    "Swiggy Restaurant",
    "Order #4471",
    "Date: 24/07/2026",
    "Butter Naan          80.00",
    "Paneer Tikka        220.00",
    "GST                  18.00",
    "Total               340.00",
    "Thank you for ordering!",
]


async def test_scan_receipt_extracts_expected_fields(client, capsys, monkeypatch):
    """No Gemini configured in tests -> exercises the real Tesseract +
    heuristic-parser path end to end."""
    token = await register_verify_login(client, capsys, email="ocr1@example.com")
    image_bytes = _render_receipt(SAMPLE_RECEIPT_LINES)

    files = {"file": ("receipt.png", io.BytesIO(image_bytes), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["source"] == "heuristic"
    assert "Swiggy" in (data["merchant"] or "")
    assert data["amount"] == "340.00"
    assert data["date"] == "2026-07-24"
    assert len(data["raw_text"]) > 0


async def test_scan_receipt_finds_line_items(client, capsys):
    token = await register_verify_login(client, capsys, email="ocr2@example.com")
    image_bytes = _render_receipt(SAMPLE_RECEIPT_LINES)

    files = {"file": ("receipt.png", io.BytesIO(image_bytes), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))
    items = resp.json()["data"]["items"]
    assert any("Naan" in item or "Tikka" in item for item in items)


async def test_scan_receipt_rejects_empty_file(client, capsys):
    token = await register_verify_login(client, capsys, email="ocr3@example.com")
    files = {"file": ("empty.png", io.BytesIO(b""), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_FILE"


async def test_scan_receipt_rejects_unreadable_file(client, capsys):
    token = await register_verify_login(client, capsys, email="ocr4@example.com")
    files = {"file": ("notreally.png", io.BytesIO(b"this is not an image at all"), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "OCR_FAILED"


async def test_scan_uses_ai_refinement_when_available(client, capsys, monkeypatch):
    token = await register_verify_login(client, capsys, email="ocr5@example.com")
    image_bytes = _render_receipt(SAMPLE_RECEIPT_LINES)

    async def fake_generate_json(system_instructions, user_prompt, **kwargs):
        assert "Swiggy" in user_prompt  # real OCR text reached the prompt
        return {"merchant": "Swiggy Restaurant", "amount": "340.00", "date": "2026-07-24", "gst": "18.00", "items": ["Butter Naan", "Paneer Tikka"]}

    monkeypatch.setattr("app.services.ocr_service.gemini_client.generate_json", fake_generate_json)

    files = {"file": ("receipt.png", io.BytesIO(image_bytes), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))
    data = resp.json()["data"]
    assert data["source"] == "ai"
    assert data["merchant"] == "Swiggy Restaurant"


async def test_scan_receipt_does_not_create_expense(client, capsys):
    """The core Phase 6 requirement: OCR returns a draft only. The user
    must separately POST /expenses to actually save anything."""
    token = await register_verify_login(client, capsys, email="ocr6@example.com")
    image_bytes = _render_receipt(SAMPLE_RECEIPT_LINES)

    files = {"file": ("receipt.png", io.BytesIO(image_bytes), "image/png")}
    await client.post("/api/v1/receipts/scan", files=files, headers=auth_headers(token))

    resp = await client.get("/api/v1/expenses", headers=auth_headers(token))
    assert resp.json()["data"]["total"] == 0


async def test_scan_receipt_requires_auth(client):
    files = {"file": ("receipt.png", io.BytesIO(b"x"), "image/png")}
    resp = await client.post("/api/v1/receipts/scan", files=files)
    assert resp.status_code == 401
