"""Master-data Pydantic schemas **and** the shared HTTP-boundary plumbing every
ops router reuses.

The project file layout gives the operations slice no dedicated ``common`` module,
so the cross-cutting boundary primitives (error envelope, pagination, the
Decimal→string money type and the per-router ``EnvelopeRoute``) live here - this
is the foundational schema module every other router imports. Keeping them in one
place is the DRY-correct home given the fixed file list.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.money import MoneyIn, MoneyStr

# ---------------------------------------------------------------------------
# ``Money``: a plain Decimal-> string serializer for NON-cents Decimal fields
# (VAT/pos_fee fractions, forecast_qty, score fractions). True monetary columns
# are integer cents and use ``MoneyIn`` (request) / ``MoneyStr`` (response) from
# :mod:`app.money`, re-exported here for the ops schema modules that import from
# this foundational module.
# ---------------------------------------------------------------------------


def _money_to_str(value: Decimal | None) -> str | None:
    """Serialize a Decimal as a plain (non-scientific) decimal string."""
    if value is None:
        return None
    return format(value, "f")


Money = Annotated[
    Decimal, PlainSerializer(_money_to_str, return_type=str, when_used="json")
]


class ApiModel(BaseModel):
    """Base model: reads from ORM attributes, forbids unknown output drift."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Error envelope + per-route rendering
# ---------------------------------------------------------------------------


class ApiException(Exception):
    """Raised anywhere below the router to yield the standard error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def api_error(
    status_code: int, code: str, message: str, details: Any | None = None
) -> ApiException:
    """Construct (caller raises) an ``ApiException`` - keeps call sites terse."""
    return ApiException(status_code, code, message, details)


_STATUS_CODE_NAMES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    502: "upstream_error",
}


def _envelope(code: str, message: str, details: Any | None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


class EnvelopeRoute(APIRoute):
    """Per-router route class that renders every error as ``{"error": {...}}``.

    This is the "HTTPException handlers per-route" mechanism: because the app
    factory (``main.py``) is frozen and cannot register global handlers, each ops
    router opts into this route class via :func:`make_router`.
    """

    def get_route_handler(self):  # noqa: ANN201 - FastAPI signature
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request):  # noqa: ANN001, ANN202
            try:
                return await original_route_handler(request)
            except ApiException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content=_envelope(exc.code, exc.message, jsonable_encoder(exc.details)),
                )
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=422,
                    content=_envelope(
                        "validation_error",
                        "Request validation failed",
                        jsonable_encoder(exc.errors()),
                    ),
                )
            except (HTTPException, StarletteHTTPException) as exc:
                code = _STATUS_CODE_NAMES.get(exc.status_code, "error")
                detail = exc.detail
                message = detail if isinstance(detail, str) else code
                extra = None if isinstance(detail, str) else jsonable_encoder(detail)
                return JSONResponse(
                    status_code=exc.status_code,
                    content=_envelope(code, message, extra),
                )

        return custom_route_handler


def make_router(*, prefix: str, tags: list[str]) -> APIRouter:
    """Build an APIRouter wired to the envelope route class."""
    return APIRouter(prefix=prefix, tags=tags, route_class=EnvelopeRoute)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    """Standard offset-pagination envelope: ``{items, total, limit, offset}``."""

    items: list[ItemT]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PaginationParams:
    """Parsed ``?limit=&offset=`` query parameters."""

    limit: int
    offset: int


def pagination(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginationParams:
    """FastAPI dependency for offset pagination (default 50, max 500)."""
    return PaginationParams(limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


class SupplierCreate(ApiModel):
    name: str = Field(min_length=1)
    email: str | None = None
    warehouse_address: str | None = None
    is_active: bool = True


class SupplierUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    email: str | None = None
    warehouse_address: str | None = None
    is_active: bool | None = None


class SupplierRead(ApiModel):
    id: int
    name: str
    email: str | None
    warehouse_address: str | None
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------------------------------------------------------------------------
# Categories (read-only)
# ---------------------------------------------------------------------------


class CategoryRead(ApiModel):
    id: int
    name: str
    display_order: int
    dispatch_print_order: int
    created_at: datetime.datetime


# ---------------------------------------------------------------------------
# Clients (+ fees, + interventions)
# ---------------------------------------------------------------------------


class ClientCreate(ApiModel):
    name: str = Field(min_length=1)
    location: str | None = None
    workers_count: int | None = Field(default=None, ge=0)
    worker_type: str | None = None
    preferences: str | None = None
    notes: str | None = None


class ClientUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    location: str | None = None
    workers_count: int | None = Field(default=None, ge=0)
    worker_type: str | None = None
    preferences: str | None = None
    notes: str | None = None


class ClientRead(ApiModel):
    id: int
    name: str
    location: str | None
    workers_count: int | None
    worker_type: str | None
    preferences: str | None
    notes: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ClientFeeCreate(ApiModel):
    yearly_fee: MoneyIn = Field(ge=0)
    contract_start: datetime.date
    contract_end: datetime.date | None = None


class ClientFeeRead(ApiModel):
    id: int
    client_id: int
    yearly_fee: MoneyStr
    contract_start: datetime.date
    contract_end: datetime.date | None


class ClientInterventionCreate(ApiModel):
    fridge_id: int
    intervention_type: str = Field(min_length=1)
    description: str | None = None
    occurred_at: datetime.datetime
    created_by: int | None = None


class ClientInterventionRead(ApiModel):
    id: int
    fridge_id: int
    intervention_type: str
    description: str | None
    occurred_at: datetime.datetime
    created_by: int | None
    created_at: datetime.datetime


# ---------------------------------------------------------------------------
# Fridges (+ delivery config)
# ---------------------------------------------------------------------------


# Manual status override (D5): NULL follows Husky, else user-forced.
FridgeLocalStatus = Literal["inactive", "cancelled"]


class FridgeCreate(ApiModel):
    husky_id: str = Field(min_length=1)
    husky_name: str | None = None
    friendly_name: str = Field(min_length=1)
    client_id: int | None = None
    delivery_address: str | None = None
    delivery_instructions: str | None = None
    is_active: bool = True
    local_status: FridgeLocalStatus | None = None


class FridgeUpdate(ApiModel):
    husky_id: str | None = Field(default=None, min_length=1)
    husky_name: str | None = None
    friendly_name: str | None = Field(default=None, min_length=1)
    client_id: int | None = None
    delivery_address: str | None = None
    delivery_instructions: str | None = None
    is_active: bool | None = None
    # Explicit null clears the override (follow Husky again); omitted = unchanged.
    local_status: FridgeLocalStatus | None = None


class FridgeRead(ApiModel):
    id: int
    husky_id: str
    husky_name: str | None
    friendly_name: str
    client_id: int | None
    delivery_address: str | None
    delivery_instructions: str | None
    is_active: bool
    local_status: FridgeLocalStatus | None
    # Effective status = local_status if set, else active/inactive from is_active.
    effective_status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DeliveryConfigItem(ApiModel):
    weekday: int = Field(ge=1, le=7)
    min_daily_qty: int = Field(ge=0)
    days_to_fill: int = Field(gt=0)


class DeliveryConfigReplace(ApiModel):
    items: list[DeliveryConfigItem]
