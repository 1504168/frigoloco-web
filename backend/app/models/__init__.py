"""SQLAlchemy models package.

Importing this package registers every table on ``Base.metadata``. The tables
mirrored from ``architecture/database/schema.sql`` are created by that SQL file;
only ``SYNC_TABLES`` (defined in ``sync.py``) is created from ORM metadata via
``create_all(checkfirst=True)`` - ``sync_run`` because schema.sql does not define
it, ``fridge_stock`` as a no-op safety net (schema.sql defines it too).
"""

from __future__ import annotations

from app.models.base import Base
from app.models.events import ProductReview, RestockEvent, SalesEvent
from app.models.master import (
    Category,
    Client,
    ClientFee,
    ClientIntervention,
    ClientServiceCharge,
    Fridge,
    FridgeDeliveryConfig,
    FridgeProductPrice,
    MenuProductCap,
    Product,
    ProductTarget,
    Setting,
    Supplier,
    User,
)
from app.models.operations import (
    Alert,
    AuditLog,
    Dispatch,
    DispatchLine,
    OrderNoCounter,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
    WeeklyFinancial,
)
from app.models.planning import (
    ForecastResult,
    ForecastRun,
    FridgeProductScore,
    MenuLine,
    MenuProduct,
    ProductScore,
    WeeklyMenu,
)
from app.models.sync import FridgeStock, SyncRun

# Sync-layer tables, created via metadata create_all(checkfirst=True). sync_run
# is NOT in schema.sql; fridge_stock is (migration 0009) - create_all skips it
# when the schema script already made it.
SYNC_TABLES = (SyncRun.__table__, FridgeStock.__table__)

__all__ = [
    "Base",
    "SYNC_TABLES",
    # master
    "User",
    "Supplier",
    "Category",
    "Product",
    "Client",
    "Fridge",
    "FridgeProductPrice",
    "FridgeDeliveryConfig",
    "ClientFee",
    "ClientServiceCharge",
    "ClientIntervention",
    "ProductTarget",
    "MenuProductCap",
    "Setting",
    # planning
    "WeeklyMenu",
    "MenuProduct",
    "MenuLine",
    "ForecastRun",
    "ForecastResult",
    "ProductScore",
    "FridgeProductScore",
    # operations
    "OrderNoCounter",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "Dispatch",
    "DispatchLine",
    "StockMovement",
    "WeeklyFinancial",
    "Alert",
    "AuditLog",
    # events
    "SalesEvent",
    "RestockEvent",
    "ProductReview",
    # sync
    "SyncRun",
    "FridgeStock",
]
