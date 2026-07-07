"""FrigoLoco scheduled-jobs package.

The APScheduler worker lives in :mod:`cron.scheduler`; every job under
:mod:`cron.jobs` is also runnable as a standalone CLI
(``python -m cron.jobs.<name>``).
"""

from __future__ import annotations

__all__: list[str] = []
