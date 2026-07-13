# FrigoLoco cron worker - APScheduler container.
# Builds the backend (editable) + cron package, then runs the scheduler.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Backend is the source of Settings, models, the DB session and app.husky.
# Copy both projects; cron depends on ../backend as an editable path dep.
COPY backend /app/backend
COPY cron /app/cron

# psycopg2-binary (a backend dep) needs no build toolchain; keep the image slim.
RUN pip install --upgrade pip \
    && pip install -e /app/backend -e /app/cron

# Raw-first ELT archive lives here unless RAW_ARCHIVE_DIR overrides it.
ENV RAW_ARCHIVE_DIR=/app/raw_archive
RUN mkdir -p /app/raw_archive

WORKDIR /app/cron

# Long-running APScheduler worker (Europe/Brussels). Individual jobs can also be
# run one-off: `docker run ... python -m cron.jobs.snapshot_stock`.
CMD ["python", "-m", "cron.scheduler"]
