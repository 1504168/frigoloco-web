"""Raw-first ELT archive: gzip every raw Husky payload before transform.

Layout (per implementation brief)::

    {settings.raw_archive_dir}/raw/husky/{endpoint}/{YYYY}/{label}.json.gz

The archive is written *before* any parse/transform so a bad transform never
loses the source-of-truth bytes; a job can be re-run against the DB from the
API, and the raw payloads remain for audit/replay.
"""

from __future__ import annotations

import datetime
import gzip
from pathlib import Path

from app.config import get_settings


def archive_raw(
    endpoint: str,
    label: str,
    raw: bytes,
    *,
    year: int | None = None,
) -> Path:
    """Gzip ``raw`` bytes to the archive and return the written path.

    Parameters
    ----------
    endpoint:
        Logical endpoint name (e.g. ``"purchases"``, ``"stock_current"``).
    label:
        Unique file label (e.g. a window ``"2026-06-26_2026-06-28"`` or a run
        timestamp). ``.json.gz`` is appended.
    raw:
        The exact response bytes as received from the vendor.
    year:
        Partition folder year; defaults to the current UTC year.
    """
    settings = get_settings()
    resolved_year = year if year is not None else datetime.datetime.now(datetime.timezone.utc).year
    dest_dir = Path(settings.raw_archive_dir) / "raw" / "husky" / endpoint / str(resolved_year)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{label}.json.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(raw)
    return path
