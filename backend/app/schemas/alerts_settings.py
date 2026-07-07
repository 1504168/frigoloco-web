"""Pydantic v2 schemas for the alerts and settings routers."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import AlertType


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: AlertType
    payload: dict
    status: str
    created_at: datetime.datetime
    acknowledged_by: int | None
    acknowledged_at: datetime.datetime | None


class SettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    description: str | None
    updated_at: datetime.datetime


class SettingUpdate(BaseModel):
    value: Any
    description: str | None = None
