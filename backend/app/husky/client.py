"""Typed httpx client for the Intelligent Fridges ("Husky") API.

* Basic auth from backend ``Settings`` (``FRIGOLOCO_API_USERNAME/PASSWORD``).
* Base URL ``{FRIGOLOCO_API_BASE_URL}/{merchant}`` - the merchant path segment
  is part of every endpoint.
* Client-side throttle to ``settings.husky_throttle_rps`` (no documented vendor
  rate limit; ~1 req/s keeps the full backfill well-behaved).
* ``tenacity`` retry ×5 with exponential backoff on 429 / 5xx / timeout.
* Each fetch returns a :class:`FetchResult` carrying **both** the raw response
  bytes (for the raw-first archive) and the parsed, typed pydantic model.
"""

from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings, get_settings
from app.husky.schemas import (
    CurrentStockResult,
    FacilitiesResult,
    FridgeProductPricesResult,
    FridgesResult,
    ProductReviewsResult,
    ProductTypesResult,
    PurchaseResult,
    RestockResult,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

_RETRYABLE_STATUS = {429}
_MAX_ATTEMPTS = 5


class RetryableHuskyError(Exception):
    """Raised for a retryable HTTP status (429 / 5xx) so tenacity can retry."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"retryable Husky response {status_code} for {url}")
        self.status_code = status_code
        self.url = url


@dataclass
class FetchResult(Generic[ModelT]):
    """A single API fetch: the raw bytes (archive) and the parsed model."""

    raw: bytes
    data: ModelT


class _RateLimiter:
    """Simple thread-safe minimum-interval throttle."""

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


def _iso(value: datetime.datetime | str | None) -> str | None:
    """Render a datetime as an ISO-8601 UTC string the API accepts."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    # The vendor rejects fractional seconds; emit whole-second ISO-8601 UTC.
    normalized = value.astimezone(datetime.timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


class HuskyClient:
    """Thin typed wrapper over the vendor REST API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.frigoloco_api_username or not self._settings.frigoloco_api_password:
            raise RuntimeError(
                "Husky credentials missing: set FRIGOLOCO_API_USERNAME / "
                "FRIGOLOCO_API_PASSWORD in the environment/.env"
            )
        merchant = self._settings.frigoloco_merchant
        base = self._settings.frigoloco_api_base_url.rstrip("/")
        self._base_url = f"{base}/{merchant}"
        self._limiter = _RateLimiter(self._settings.husky_throttle_rps)
        self._client = httpx.Client(
            auth=(
                self._settings.frigoloco_api_username,
                self._settings.frigoloco_api_password,
            ),
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={"Accept": "application/json"},
        )

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HuskyClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- low-level ----------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((RetryableHuskyError, httpx.TimeoutException, httpx.TransportError)),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self._limiter.wait()
        url = f"{self._base_url}{path}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        response = self._client.get(url, params=clean_params)
        if response.status_code in _RETRYABLE_STATUS or response.status_code >= 500:
            raise RetryableHuskyError(response.status_code, str(response.url))
        response.raise_for_status()
        return response

    def _fetch(
        self,
        path: str,
        params: dict[str, Any] | None,
        model: type[ModelT],
    ) -> FetchResult[ModelT]:
        response = self._get(path, params)
        raw = response.content
        parsed = model.model_validate(response.json())
        return FetchResult(raw=raw, data=parsed)

    # -- endpoints ----------------------------------------------------------

    def get_purchases(
        self,
        window_from: datetime.datetime | str | None = None,
        window_to: datetime.datetime | str | None = None,
        fridge: str | None = None,
    ) -> FetchResult[PurchaseResult]:
        params = {"from": _iso(window_from), "to": _iso(window_to), "fridge": fridge}
        return self._fetch("/purchases", params, PurchaseResult)

    def get_restock(
        self,
        window_from: datetime.datetime | str | None = None,
        window_to: datetime.datetime | str | None = None,
        fridge: str | None = None,
        status: str | None = None,
        action: str | None = None,
    ) -> FetchResult[RestockResult]:
        params = {
            "from": _iso(window_from),
            "to": _iso(window_to),
            "fridge": fridge,
            "status": status,
            "action": action,
        }
        return self._fetch("/restock", params, RestockResult)

    def get_stock_current(self, fridge: str | None = None) -> FetchResult[CurrentStockResult]:
        return self._fetch("/stock/current", {"fridge": fridge}, CurrentStockResult)

    def get_product_reviews(
        self,
        window_from: datetime.datetime | str | None = None,
        window_to: datetime.datetime | str | None = None,
        fridge: str | None = None,
    ) -> FetchResult[ProductReviewsResult]:
        params = {"from": _iso(window_from), "to": _iso(window_to), "fridge": fridge}
        return self._fetch("/productreview", params, ProductReviewsResult)

    def get_product_types(self, product_code: str | None = None) -> FetchResult[ProductTypesResult]:
        return self._fetch("/producttype", {"productCode": product_code}, ProductTypesResult)

    def get_fridges(self, fridge: str | None = None) -> FetchResult[FridgesResult]:
        return self._fetch("/fridge", {"fridge": fridge}, FridgesResult)

    def get_facilities(self, name: str | None = None) -> FetchResult[FacilitiesResult]:
        return self._fetch("/facility", {"name": name}, FacilitiesResult)

    def get_fridge_product_prices(
        self,
        fridge: str | None = None,
        product_code: str | None = None,
    ) -> FetchResult[FridgeProductPricesResult]:
        params = {"fridge": fridge, "productCode": product_code}
        return self._fetch("/fridgeproductprice", params, FridgeProductPricesResult)
