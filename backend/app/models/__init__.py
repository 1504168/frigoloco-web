"""SQLAlchemy models package.

Importing this package registers every table on ``Base.metadata``. The 34 tables
mirrored from ``architecture/database/schema.sql`` are created by that SQL file;
only ``SYNC_TABLES`` (defined in ``sync.py``, absent from schema.sql) are meant
to be created from ORM metadata via ``create_all``.
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
    RestockVerification,
    RestockVerificationLine,
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
from app.models.sync import StockSnapshot, SyncRun

# The two tables NOT in schema.sql - created via metadata create_all().
SYNC_TABLES = (SyncRun.__table__, StockSnapshot.__table__)

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
    "RestockVerification",
    "RestockVerificationLine",
    "WeeklyFinancial",
    "Alert",
    "AuditLog",
    # events
    "SalesEvent",
    "RestockEvent",
    "ProductReview",
    # sync
    "SyncRun",
    "StockSnapshot",
]
