"""Cascade (dependent-dropdown) option schemas: Category -> Brand -> Product.

Minimal ``id``/``name`` payloads meant to populate the three dependent dropdowns
one call each. Full CRUD records live in the resource routers (``products``,
``suppliers``, ``categories``); these are deliberately read-only option lists.
"""

from __future__ import annotations

from app.schemas.masters import ApiModel


class CategoryOption(ApiModel):
    id: int
    name: str
    # The numeric prefix (1..10) the UI sorts on - NOT the text name, which would
    # order "10" before "2".
    display_order: int


class BrandOption(ApiModel):
    id: int
    name: str


class ProductOption(ApiModel):
    id: int
    code: str
    name: str
