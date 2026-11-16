"""Pydantic v2 schemas for the operations reports: restock (#56) and loss (#57)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from app.money import MoneyStr


class RestockReportRow(BaseModel):
    delivery_date: datetime.date
    fridge_id: int
    fridge_name: str
    product_id: int
    product_code: str
    product_name: str
    category: str
    dispatched_qty: int
    added_qty: int
    # added_qty - dispatched_qty: negative means units dispatched but never scanned in.
    gap_qty: int


class RestockReportRead(BaseModel):
    date_from: datetime.date
    date_to: datetime.date
    rows: list[RestockReportRow]
    total_dispatched_qty: int
    total_added_qty: int
    total_gap_qty: int


class LossReportRow(BaseModel):
    iso_year: int
    iso_week: int
    week_start: datetime.date
    fridge_id: int
    fridge_name: str
    product_id: int
    product_code: str
    product_name: str
    category: str
    removed_qty: int
    unit_purchase_price: MoneyStr
    loss_cost: MoneyStr


class LossReportRead(BaseModel):
    date_from: datetime.date
    date_to: datetime.date
    rows: list[LossReportRow]
    total_removed_qty: int
    total_loss_cost: MoneyStr
