# FrigoLoco backend - FastAPI (Uvicorn) service.
# Build context is the backend/ directory (Railway: Root Directory = backend/).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package first (deps rarely change -> better layer caching), then
# the source. scripts/ ships too so DB migrations can be run one-off in the
# container (`python scripts/apply_migration.py ...`).
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts

# psycopg2-binary needs no build toolchain; the slim image stays small.
RUN pip install --upgrade pip \
    && pip install -e .

# Raw-first ELT archive lands here unless RAW_ARCHIVE_DIR overrides it. On
# Railway this path is ephemeral (attach a volume to persist raw payloads).
ENV RAW_ARCHIVE_DIR=/app/raw_archive
RUN mkdir -p /app/raw_archive

# Railway injects $PORT at runtime; fall back to 8000 for local `docker run`.
# JSON exec form wrapping `sh -c` so ${PORT} is expanded; `exec` hands PID 1 to
# uvicorn so it receives SIGTERM directly for graceful shutdown on redeploy.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
