FROM python:3.12-slim

WORKDIR /app

# System deps: build-essential/libpq-dev for psycopg (Postgres driver) and
# argon2-cffi, tesseract-ocr for Phase 6 receipt scanning (pytesseract is
# only a thin Python wrapper — the actual OCR engine is this system binary,
# and the app will 422 on every /receipts/scan call without it).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run migrations then start the server. In production, split this into a
# separate migration job/step rather than running it on every container start.
#
# --workers is deliberately 1, not a scaling knob left at its default: Diary
# and Vault unlock sessions live in this process's memory
# (app/services/unlock_session_store.py). Running multiple workers or
# multiple container replicas would split that state across processes that
# can't see each other's unlocks — a real, silent correctness bug, not a
# performance one. Scaling beyond one process requires moving that store to
# Redis first (noted in docs/02e-database-er-phase6.md).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
