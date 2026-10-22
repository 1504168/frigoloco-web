"""Pydantic v2 schemas for the alerts and settings routers."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import AlertType


class StockBlockedLine(BaseModel):
    """One product the blocked dispatch asked for more of than the warehouse held."""

    product_id: int
    product_name: str
    requested: int
    available: int


class AlertDispatchRef(BaseModel):
    """The dispatch an alert is about, keyed the way the Dispatch page URL is."""

    dispatch_id: int
    delivery_date: datetime.date
    iso_year: int
    iso_week: int
    day_name: str


class StockBlockedDetails(BaseModel):
    """Readable form of a ``negative_blocked`` payload, resolved at read time."""

    dispatch: AlertDispatchRef | None  # None when the dispatch was deleted since
    lines: list[StockBlockedLine]
    occurrences: int
    last_raised_at: datetime.datetime


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: AlertType
    payload: dict
    status: str
    created_at: datetime.datetime
    acknowledged_by: int | None
    acknowledged_at: datetime.datetime | None
    stock_blocked: StockBlockedDetails | None = None


class SettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    description: str | None
    updated_at: datetime.datetime


class SettingUpdate(BaseModel):
    value: Any
    description: str | None = None
