"""Status/type domains as Python enums, bound to VARCHAR + CHECK columns.

Decision (2026-07-03, migration 0003): FrigoLoco no longer uses native
PostgreSQL ENUM types. Every former enum column is a plain ``TEXT``/VARCHAR
column guarded by a NAMED ``CHECK`` constraint listing the allowed values.

Why: native PG enums are painful to evolve (adding/removing/reordering a value
needs ``ALTER TYPE`` and cannot run inside some transactions; dropping a value
is impossible), they leak the type name into every constraint/rule/view
dependency, and they buy nothing over a ``TEXT + CHECK`` pair for our small,
rarely-changing domains. ``native_enum=False`` maps the Python enum to a VARCHAR
column; ``create_constraint=False`` stops SQLAlchemy emitting its own unnamed
CHECK - the authoritative, NAMED CHECK lives in ``schema.sql`` (and, mirrored,
in each model's ``__table_args__`` via :func:`enum_check`).
"""

from __future__ import annotations

import enum
from typing import Type

from sqlalchemy import CheckConstraint
from sqlalchemy import Enum as SAEnum


def text_enum(python_enum: Type[enum.Enum], type_name: str) -> SAEnum:
    """Bind a Python enum to a VARCHAR column (no native PG ENUM type).

    ``native_enum=False`` stores the enum *values* as strings in a VARCHAR
    column. ``create_constraint=False`` prevents SQLAlchemy from emitting its
    own (unnamed) CHECK - the NAMED CHECK is declared explicitly in the model's
    ``__table_args__`` via :func:`enum_check` and in ``schema.sql``.
    """
    return SAEnum(
        python_enum,
        name=type_name,
        native_enum=False,
        create_constraint=False,
        values_callable=lambda members: [member.value for member in members],
    )


def enum_check(column: str, python_enum: Type[enum.Enum], name: str) -> CheckConstraint:
    """Build a NAMED CHECK constraint restricting ``column`` to the enum values.

    Keeps the model's declared CHECK in lock-step with the values migration
    0003 writes into the live DB, so the ORM and ``schema.sql`` never drift.
    """
    allowed = ", ".join(f"'{member.value}'" for member in python_enum)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class UserRole(str, enum.Enum):
    admin = "admin"
    ops_manager = "ops_manager"
    warehouse = "warehouse"
    driver = "driver"
    finance = "finance"


class PoStatus(str, enum.Enum):
    pending = "pending"
    received = "received"
    cancelled = "cancelled"


class DispatchStatus(str, enum.Enum):
    draft = "draft"
    saved = "saved"
    dispatched = "dispatched"
    reconciled = "reconciled"


class StockMovementType(str, enum.Enum):
    po_receipt = "po_receipt"
    dispatch = "dispatch"
    adjustment = "adjustment"
    cancellation_reversal = "cancellation_reversal"


class MenuStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class RestockAction(str, enum.Enum):
    added = "added"
    removed = "removed"


class TagStatus(str, enum.Enum):
    valid = "valid"
    unreliable = "unreliable"
    unrecognised = "unrecognised"


class LineSource(str, enum.Enum):
    forecast = "forecast"
    manual = "manual"


class AlertType(str, enum.Enum):
    expiry = "expiry"
    low_stock = "low_stock"
    below_target = "below_target"
    negative_blocked = "negative_blocked"
    rfid_offline = "rfid_offline"


# Reusable SQLAlchemy type instances - VARCHAR-backed (native_enum=False).
USER_ROLE_ENUM = text_enum(UserRole, "user_role")
PO_STATUS_ENUM = text_enum(PoStatus, "po_status")
DISPATCH_STATUS_ENUM = text_enum(DispatchStatus, "dispatch_status")
STOCK_MOVEMENT_TYPE_ENUM = text_enum(StockMovementType, "stock_movement_type")
MENU_STATUS_ENUM = text_enum(MenuStatus, "menu_status")
RESTOCK_ACTION_ENUM = text_enum(RestockAction, "restock_action")
TAG_STATUS_ENUM = text_enum(TagStatus, "tag_status")
LINE_SOURCE_ENUM = text_enum(LineSource, "line_source")
ALERT_TYPE_ENUM = text_enum(AlertType, "alert_type")
