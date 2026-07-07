"""Typed Husky response models (pinned columns, forward-compatible).

Design notes
------------
* Every response model sets ``extra='allow'`` so the vendor can add fields
  without breaking ingestion — we only pin the columns we actually read.
* Prices arrive as ``int64`` *minor units* (cents); the euro conversion lives in
  :mod:`app.husky.normalize` (``minor_units_to_euros``), not here.
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Response models — pinned columns only, extra='allow' for forward-compat.
# ---------------------------------------------------------------------------

_MODEL_CONFIG = ConfigDict(extra="allow", populate_by_name=True)


class _HuskyModel(BaseModel):
    model_config = _MODEL_CONFIG


class CommonFridge(_HuskyModel):
    name: str | None = None
    description: str | None = None
    friendlyName: str | None = None
    facility: str | None = None
    reference: str | None = None
    serialNumber: str | None = None
    status: str | None = None


# --- /purchases -------------------------------------------------------------


class PurchaseProduct(_HuskyModel):
    tagId: str | None = None
    epc: str | None = None
    name: str | None = None
    productCode: str | None = None
    productCategory: str | None = None
    productBrand: str | None = None
    price: int | None = None
    priceExSurcharges: int | None = None
    vat: float | None = None
    expiryDate: datetime.datetime | None = None
    discounts: list[dict[str, Any]] = Field(default_factory=list)
    refundStatus: list[dict[str, Any]] = Field(default_factory=list)


class Purchase(_HuskyModel):
    id: str | None = None
    reportingDate: datetime.datetime | None = None
    purchaseDate: datetime.datetime | None = None
    type: str | None = None
    amount: int | None = None
    products: list[PurchaseProduct] = Field(default_factory=list)
    purchaseStatus: list[dict[str, Any]] = Field(default_factory=list)


class PurchaseFridge(_HuskyModel):
    name: str | None = None
    description: str | None = None
    friendlyName: str | None = None
    facility: str | None = None
    purchases: list[Purchase] = Field(default_factory=list)


class PurchaseResult(_HuskyModel):
    from_: datetime.datetime | None = Field(default=None, alias="from")
    to: datetime.datetime | None = None
    merchantName: str | None = None
    fridges: dict[str, PurchaseFridge] = Field(default_factory=dict)


# --- /restock ---------------------------------------------------------------


class RestockTag(_HuskyModel):
    tagId: str | None = None
    epc: str | None = None
    productName: str | None = None
    productCode: str | None = None
    productCategory: str | None = None
    status: str | None = None  # VALID | UNRECOGNISED | UNRELIABLE
    action: str | None = None  # ADDED | REMOVED | UNCHANGED
    expiryDate: datetime.datetime | None = None


class RestockSession(_HuskyModel):
    reportingDate: datetime.datetime | None = None
    startDate: datetime.datetime | None = None
    endDate: datetime.datetime | None = None
    restocker: str | None = None
    fridge: CommonFridge | None = None
    tags: list[RestockTag] = Field(default_factory=list)


class RestockResult(_HuskyModel):
    from_: datetime.datetime | None = Field(default=None, alias="from")
    to: datetime.datetime | None = None
    merchantName: str | None = None
    sessions: dict[str, RestockSession] = Field(default_factory=dict)


# --- /stock/current ---------------------------------------------------------


class StockTag(_HuskyModel):
    tagId: str | None = None
    epc: str | None = None
    expiryDate: datetime.datetime | None = None
    purchaseId: str | None = None
    purchaseDate: datetime.datetime | None = None


class StockedProduct(_HuskyModel):
    productCode: str | None = None
    productName: str | None = None
    productCategory: str | None = None
    productBrand: str | None = None
    purchased: list[StockTag] = Field(default_factory=list)
    current: list[StockTag] = Field(default_factory=list)


class CurrentStock(_HuskyModel):
    fridge: CommonFridge | None = None
    lastModification: datetime.datetime | None = None
    lastRestocker: str | None = None
    products: list[StockedProduct] = Field(default_factory=list)


class CurrentStockResult(_HuskyModel):
    merchantName: str | None = None
    lastModification: datetime.datetime | None = None
    current: list[CurrentStock] = Field(default_factory=list)


# --- /productreview ---------------------------------------------------------


class ReviewProduct(_HuskyModel):
    tagId: str | None = None
    epc: str | None = None
    name: str | None = None
    productCode: str | None = None
    reference: str | None = None


class ProductReviewItem(_HuskyModel):
    rating: int | None = None
    review: str | None = None
    category: str | None = None
    reviewDate: datetime.datetime | None = None
    purchaseId: str | None = None
    purchaseDate: datetime.datetime | None = None
    userEmailAddress: str | None = None
    product: ReviewProduct | None = None
    fridge: CommonFridge | None = None


class ProductReviewsResult(_HuskyModel):
    from_: datetime.datetime | None = Field(default=None, alias="from")
    to: datetime.datetime | None = None
    merchantName: str | None = None
    productReviews: list[ProductReviewItem] = Field(default_factory=list)


# --- /producttype -----------------------------------------------------------


class ProductTypeItem(_HuskyModel):
    name: str | None = None
    description: str | None = None
    productCode: str | None = None
    productCategory: str | None = None
    productBrand: str | None = None
    productPackage: str | None = None
    productDeposit: str | None = None
    reference: str | None = None
    expiryDays: int | None = None
    currencyCode: str | None = None
    price: int | None = None
    priceExSurcharges: int | None = None
    vat: float | None = None
    createdAt: datetime.datetime | None = None


class ProductTypesResult(_HuskyModel):
    generated: datetime.datetime | None = None
    merchantName: str | None = None
    productTypes: list[ProductTypeItem] = Field(default_factory=list)


# --- /fridge ----------------------------------------------------------------


class FridgeItem(_HuskyModel):
    name: str | None = None
    description: str | None = None
    friendlyName: str | None = None
    facility: str | None = None
    reference: str | None = None
    serialNumber: str | None = None
    status: str | None = None
    fridgeGroups: list[str] = Field(default_factory=list)


class FridgesResult(_HuskyModel):
    generated: datetime.datetime | None = None
    merchantName: str | None = None
    fridges: list[FridgeItem] = Field(default_factory=list)


# --- /facility --------------------------------------------------------------


class LocationModel(_HuskyModel):
    address: str | None = None
    zipPostalCode: str | None = None
    city: str | None = None
    stateProvince: str | None = None
    countryCode: str | None = None


class ContactModel(_HuskyModel):
    name: str | None = None
    emailAddress: str | None = None
    telephoneNumber: str | None = None


class FacilityItem(_HuskyModel):
    name: str | None = None
    description: str | None = None
    reference: str | None = None
    openingHours: str | None = None
    deliveryInstructions: str | None = None
    location: LocationModel | None = None
    contact: ContactModel | None = None
    operator: str | None = None
    fridges: list[CommonFridge] = Field(default_factory=list)


class FacilitiesResult(_HuskyModel):
    generated: datetime.datetime | None = None
    merchantName: str | None = None
    facilities: list[FacilityItem] = Field(default_factory=list)


# --- /fridgeproductprice ----------------------------------------------------


class ProductPriceItem(_HuskyModel):
    productCode: str | None = None
    currencyCode: str | None = None
    price: int | None = None
    priceExSurcharges: int | None = None
    vat: float | None = None
    createdAt: datetime.datetime | None = None


class ProductFridgeItem(_HuskyModel):
    name: str | None = None
    description: str | None = None
    friendlyName: str | None = None
    facility: str | None = None
    prices: list[ProductPriceItem] = Field(default_factory=list)


class FridgeProductPricesResult(_HuskyModel):
    generated: datetime.datetime | None = None
    merchantName: str | None = None
    fridges: list[ProductFridgeItem] = Field(default_factory=list)
