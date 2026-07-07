"""FastAPI application entry point.

Boots standalone: router modules are contributed by other agents and are
auto-discovered from the ``app.routers`` package; their absence never blocks
startup. ``/health`` reports DB reachability without failing when the DB is down.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import routers as routers_package
from app.db import engine

app = FastAPI(title="FrigoLoco API")

# CORS: allow all for now (locked down in a later phase).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _database_reachable() -> bool:
    """Return True if a trivial query against the DB succeeds."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe: always 200, with DB reachability flag."""
    reachable = _database_reachable()
    return {"status": "ok" if reachable else "degraded", "db": reachable}


def _include_discovered_routers() -> None:
    """Import every module under app.routers and include its ``router`` if any.

    Missing/broken router modules must never prevent the app from booting, so each
    import is guarded individually.
    """
    for module_info in pkgutil.iter_modules(routers_package.__path__):
        try:
            module = importlib.import_module(
                f"{routers_package.__name__}.{module_info.name}"
            )
        except ImportError:
            continue
        candidate = getattr(module, "router", None)
        if isinstance(candidate, APIRouter):
            app.include_router(candidate)


_include_discovered_routers()
