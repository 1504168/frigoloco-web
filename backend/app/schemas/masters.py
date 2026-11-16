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
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models.enums import ClientContactRole
from app.models.master import (
    ClientRuleType,
    EquipmentCategory,
    EquipmentOwnership,
    SupplierAgreementBasis,
)
from app.money import MoneyIn, MoneyStr

TAG_FORMAT = re.compile(r"^[a-z0-9_]+$")
TAG_SEPARATORS = re.compile(r"[\s-]+")
# NOT NULL columns a partial update may leave out but never set to null.
FRIDGE_NOT_NULL_FIELDS = (
    "husky_id",
    "friendly_name",
    "is_active",
    "active_on_weekends",
    "night_delivery_ok",
)
SUPPLIER_NOT_NULL_FIELDS = (
    "name",
    "payment_terms_end_of_month",
    "is_active",
)

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


def reject_explicit_nulls(body: BaseModel, not_null_fields: tuple[str, ...]) -> None:
    """A partial update may omit a NOT NULL column but must not send it as null."""
    for field_name in not_null_fields:
        if field_name in body.model_fields_set and getattr(body, field_name) is None:
            raise ValueError(f"{field_name} cannot be null")


class TextEnumBody(ApiModel):
    """Request body whose enum fields map to TEXT + CHECK columns: dump plain strings."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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
    contact_name: str | None = None
    contact_phone: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0)
    payment_terms_end_of_month: bool = False
    is_active: bool = True


class SupplierUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    email: str | None = None
    warehouse_address: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0)
    payment_terms_end_of_month: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check_not_null_fields(self) -> SupplierUpdate:
        reject_explicit_nulls(self, SUPPLIER_NOT_NULL_FIELDS)
        return self


class SupplierRead(ApiModel):
    id: int
    name: str
    email: str | None
    warehouse_address: str | None
    contact_name: str | None
    contact_phone: str | None
    payment_terms_days: int | None
    payment_terms_end_of_month: bool
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SupplierCategoryLink(ApiModel):
    """One supplier that has at least one product in one category."""

    supplier_id: int
    category_id: int


class SupplierAgreementCreate(TextEnumBody):
    year: int = Field(ge=2000, le=2100)
    discount_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    basis: SupplierAgreementBasis
    review_date: datetime.date | None = None
    notes: str | None = None


class SupplierAgreementRead(ApiModel):
    id: int
    supplier_id: int
    year: int
    discount_pct: Money
    basis: SupplierAgreementBasis
    review_date: datetime.date | None
    notes: str | None


class SupplierDeliveryScheduleItem(ApiModel):
    """Deliveries on ``delivery_weekday`` need the order in by cutoff weekday + time."""

    delivery_weekday: int = Field(ge=1, le=7)
    cutoff_weekday: int = Field(ge=1, le=7)
    cutoff_time: datetime.time


class SupplierDeliveryScheduleReplace(ApiModel):
    items: list[SupplierDeliveryScheduleItem]


class SupplierNextDeliveryRead(ApiModel):
    delivery_date: datetime.date
    order_deadline: datetime.datetime


# ---------------------------------------------------------------------------
# Categories (read-only)
# ---------------------------------------------------------------------------


class CategoryRead(ApiModel):
    id: int
    name: str
    display_order: int
    dispatch_print_order: int
    created_at: datetime.datetime
    # False = a historic category: no product in it is active any more.
    has_active_products: bool = True


# ---------------------------------------------------------------------------
# Clients (+ fees, + contacts)
# ---------------------------------------------------------------------------


class ClientCreate(ApiModel):
    name: str = Field(min_length=1)
    location: str | None = None
    preferences: str | None = None
    notes: str | None = None


class ClientUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    location: str | None = None
    preferences: str | None = None
    notes: str | None = None


class ClientRead(ApiModel):
    id: int
    name: str
    location: str | None
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


class ClientRuleCreate(TextEnumBody):
    """``fridge_id`` null = the rule applies to every fridge of the client."""

    fridge_id: int | None = None
    rule_type: ClientRuleType
    tag: str | None = None
    note: str | None = None
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None

    @field_validator("tag")
    @classmethod
    def _normalize_tag(cls, tag: str | None) -> str | None:
        if tag is None:
            return None
        return normalize_tag(tag)

    @model_validator(mode="after")
    def _check_rule_fields(self) -> ClientRuleCreate:
        if self.rule_type == ClientRuleType.exclude_tag.value and self.tag is None:
            raise ValueError("An exclude_tag rule needs a tag")
        if self.rule_type == ClientRuleType.note.value and not self.note:
            raise ValueError("A note rule needs a note")
        if self.rule_type == ClientRuleType.note.value and self.tag is not None:
            raise ValueError("A note rule has no tag")
        has_both_dates = self.valid_from is not None and self.valid_to is not None
        if has_both_dates and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self


class ClientRuleRead(ApiModel):
    id: int
    client_id: int
    fridge_id: int | None
    rule_type: ClientRuleType
    tag: str | None
    note: str | None
    valid_from: datetime.date | None
    valid_to: datetime.date | None
    created_at: datetime.datetime


class ClientRuleViolation(ApiModel):
    """A product on a fridge whose client excludes one of the product's tags."""

    fridge_id: int
    product_id: int
    rule_id: int
    tag: str
    note: str | None


class ProductTagsReplace(ApiModel):
    tags: list[str]

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized_tags = {normalize_tag(tag) for tag in tags}
        return sorted(normalized_tags)


class ClientContactItem(ApiModel):
    """One client contact; a role sent with every field empty is removed."""

    role: ClientContactRole
    name: str | None = None
    job_title: str | None = None
    phone: str | None = None
    email: str | None = None


class ClientContactsReplace(ApiModel):
    items: list[ClientContactItem]


# ---------------------------------------------------------------------------
# Fridges (+ delivery config, + interventions)
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
    modem_number: str | None = None
    sim_card_number: str | None = None
    active_on_weekends: bool = True
    preferences: str | None = None
    delivery_time_from: datetime.time | None = None
    delivery_time_to: datetime.time | None = None
    night_delivery_ok: bool = False


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
    modem_number: str | None = None
    sim_card_number: str | None = None
    active_on_weekends: bool | None = None
    preferences: str | None = None
    delivery_time_from: datetime.time | None = None
    delivery_time_to: datetime.time | None = None
    night_delivery_ok: bool | None = None

    @model_validator(mode="after")
    def _check_not_null_fields(self) -> FridgeUpdate:
        reject_explicit_nulls(self, FRIDGE_NOT_NULL_FIELDS)
        return self


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
    modem_number: str | None
    sim_card_number: str | None
    active_on_weekends: bool
    # Raw Husky status (LIVE, SHIPPED, END_OF_LIFE, ...); null until the next catalogue sync.
    husky_status: str | None
    preferences: str | None
    delivery_time_from: datetime.time | None
    delivery_time_to: datetime.time | None
    night_delivery_ok: bool
    delivery_weekdays: list[int] = []  # ISO 1-7 (Mon..Sun) this fridge gets deliveries
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DeliveryConfigItem(ApiModel):
    weekday: int = Field(ge=1, le=7)
    min_daily_qty: int = Field(ge=0)
    days_to_fill: int = Field(gt=0)


class DeliveryConfigReplaceItem(ApiModel):
    """Input row: ``days_to_fill`` is derived server-side from the rotation."""

    weekday: int = Field(ge=1, le=7)
    min_daily_qty: int = Field(ge=0)


class DeliveryConfigReplace(ApiModel):
    items: list[DeliveryConfigReplaceItem]


class FridgeInterventionCreate(ApiModel):
    intervention_type: str = Field(min_length=1)
    description: str | None = None
    occurred_at: datetime.datetime


class FridgeInterventionRead(ApiModel):
    id: int
    fridge_id: int
    intervention_type: str
    description: str | None
    occurred_at: datetime.datetime
    created_by: int | None
    created_at: datetime.datetime


# ---------------------------------------------------------------------------
# Equipment register
# ---------------------------------------------------------------------------


class EquipmentCreate(TextEnumBody):
    machine_type: str = Field(min_length=1)
    equipment_category: EquipmentCategory
    machine_code: str = Field(min_length=1)
    supplier_id: int | None = None
    client_id: int | None = None
    fridge_id: int | None = None
    ownership: EquipmentOwnership
    # Euro amounts on the wire, dumped under the *_cents column names (by_alias=True).
    purchase_price: MoneyIn | None = Field(
        default=None, ge=0, serialization_alias="purchase_price_cents"
    )
    monthly_rent_cost: MoneyIn | None = Field(
        default=None, ge=0, serialization_alias="monthly_rent_cost_cents"
    )
    monthly_fee: MoneyIn | None = Field(default=None, ge=0, serialization_alias="monthly_fee_cents")
    purchase_date: datetime.date | None = None
    financing_years: int | None = Field(default=None, gt=0)
    financing_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    financed_by: str | None = None
    is_active: bool = True
    notes: str | None = None


class EquipmentRead(ApiModel):
    id: int
    machine_type: str
    equipment_category: EquipmentCategory
    machine_code: str
    supplier_id: int | None
    client_id: int | None
    fridge_id: int | None
    ownership: EquipmentOwnership
    purchase_price: MoneyStr | None = Field(validation_alias="purchase_price_cents")
    monthly_rent_cost: MoneyStr | None = Field(validation_alias="monthly_rent_cost_cents")
    monthly_fee: MoneyStr | None = Field(validation_alias="monthly_fee_cents")
    purchase_date: datetime.date | None
    financing_years: int | None
    financing_rate: Money | None
    financed_by: str | None
    is_active: bool
    notes: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


def normalize_tag(raw_tag: str) -> str:
    """'Contains pork' -> 'contains_pork'; raises ValueError when other characters remain."""
    tag = TAG_SEPARATORS.sub("_", raw_tag.strip().lower())
    if not TAG_FORMAT.match(tag):
        raise ValueError(f"Tag '{raw_tag}' may only use letters a-z, digits and underscores")
    return tag
