"""Individual cron jobs.

Each module exposes a ``run(...)`` function (called by the scheduler) and a
``main(argv=None)`` CLI entry point (``python -m cron.jobs.<name>``). Shared
scaffolding - the ``sync_run`` bookkeeping context, DB session helper and the
fridge/product resolvers - lives in :mod:`cron.jobs._base`.
"""

from __future__ import annotations

__all__: list[str] = []
