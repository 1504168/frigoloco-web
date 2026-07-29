"""Application settings.

Loads the repo-root ``.env`` explicitly via python-dotenv BEFORE the pydantic
``Settings`` object is instantiated, so every env var (in particular ``DB_URL``,
which already lives in the repo-root ``.env``) is present in ``os.environ`` when
pydantic-settings reads it. The env_file mechanism of pydantic-settings is kept
as a secondary fallback, but the explicit ``load_dotenv`` call is the source of
truth per project convention.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> app -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

# Per-environment overlay files, selected by APP_ENV (production / test). The
# overlay holds only what DIFFERS from the base .env (typically DB_URL); shared
# secrets (FRIGOLOCO_API_*, PA_WEBHOOK_*) stay in the base .env and are inherited.
APP_ENV = os.environ.get("APP_ENV", "").strip().lower()
_ENV_OVERLAY_FILES = {
    "production": ".env.production",
    "prod": ".env.production",
    "test": ".env.test",
    "testing": ".env.test",
}
OVERLAY_ENV_FILE = (
    REPO_ROOT / _ENV_OVERLAY_FILES[APP_ENV] if APP_ENV in _ENV_OVERLAY_FILES else None
)

# Load the overlay FIRST (override=False means first-loaded wins), then the base
# .env fills in every value the overlay did not set. Real process env vars
# (e.g. Railway-injected DATABASE_URL) are already in os.environ and always win.
if OVERLAY_ENV_FILE is not None:
    load_dotenv(dotenv_path=OVERLAY_ENV_FILE, override=False)
load_dotenv(dotenv_path=ENV_FILE, override=False)


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / repo-root .env."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database -----------------------------------------------------------
    # DATABASE_URL accepted as fallback: Railway injects it by default.
    db_url: str = Field(validation_alias=AliasChoices("DB_URL", "DATABASE_URL"))

    # --- Intelligent Fridges ("Husky") API ---------------------------------
    frigoloco_api_base_url: str = Field(
        default="https://api.intelligentfridges.com/api/v1",
        validation_alias="FRIGOLOCO_API_BASE_URL",
    )
    frigoloco_api_username: str | None = Field(
        default=None, validation_alias="FRIGOLOCO_API_USERNAME"
    )
    frigoloco_api_password: str | None = Field(
        default=None, validation_alias="FRIGOLOCO_API_PASSWORD"
    )
    frigoloco_merchant: str = Field(
        default="frigoloco",
        # CLAUDE.md documents FRIGOLOCO_MERCHANT_NAME; accept the FRIGOLOCO_API_
        # prefixed variant too so either convention resolves.
        validation_alias=AliasChoices("FRIGOLOCO_MERCHANT_NAME", "FRIGOLOCO_API_MERCHANT"),
    )

    # --- Raw-first ELT archive ---------------------------------------------
    raw_archive_dir: str = Field(
        default="./raw_archive", validation_alias="RAW_ARCHIVE_DIR"
    )

    # --- Historical backfill / sync tuning ----------------------------------
    backfill_from: date | None = Field(default=None, validation_alias="BACKFILL_FROM")
    husky_throttle_rps: float = Field(
        default=1.0, validation_alias="HUSKY_THROTTLE_RPS"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (constructed once per process)."""
    return Settings()
