"""Pydantic v2 schemas for restock verification / reconciliation (R9)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.orders import MoneyStr


class VerificationLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fridge_id: int
    product_id: int
    dispatched_qty: int
    added_qty: int
    unreliable_qty: int
    diff_qty: int
    diff_value: MoneyStr


class CategoryReconTotal(BaseModel):
    category_id: int
    dispatched_qty: int
    added_qty: int
    unreliable_qty: int
    diff_qty: int
    diff_value: MoneyStr


class VerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispatch_id: int
    run_at: datetime.datetime
    lines: list[VerificationLineRead]
    category_totals: list[CategoryReconTotal]


class VerificationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispatch_id: int
    run_at: datetime.datetime
