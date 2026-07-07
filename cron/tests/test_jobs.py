"""Unit tests for the Husky normalisation layer and pure job helpers.

No live calls: everything here runs against inline/recorded fixtures. The
network client, DB session and scheduler are never touched.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.husky.normalize import (
    euros_to_minor_units,
    first_discount_provider,
    is_refunded,
    minor_units_to_euros,
    normalize_vat_fraction,
    parse_decimal,
    sum_discount_paid,
)
from app.husky.schemas import PurchaseResult, RestockResult


# --- cents -> Decimal euros -------------------------------------------------


@pytest.mark.parametrize(
    "cents, expected",
    [
        (0, Decimal("0.00")),
        (1, Decimal("0.01")),
        (150, Decimal("1.50")),
        (12345, Decimal("123.45")),
        (-250, Decimal("-2.50")),
        ("399", Decimal("3.99")),  # stringified integer from CSV path
    ],
)
def test_minor_units_to_euros(cents, expected):
    result = minor_units_to_euros(cents)
    assert result == expected
    assert isinstance(result, Decimal)


def test_minor_units_none_passthrough():
    assert minor_units_to_euros(None) is None


def test_minor_units_exact_no_float_drift():
    # 0.1 + 0.2 style drift must not appear via the Decimal path.
    assert minor_units_to_euros(10) + minor_units_to_euros(20) == Decimal("0.30")


# --- comma-decimal strings --------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,50", Decimal("1.50")),
        ("1.50", Decimal("1.50")),
        ("1.234,50", Decimal("1234.50")),  # European thousands + decimal
        ("0,06", Decimal("0.06")),
        (2, Decimal("2")),
        (2.5, Decimal("2.5")),
        (Decimal("3.14"), Decimal("3.14")),
        ("", None),
        (None, None),
    ],
)
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == expected


def test_parse_decimal_invalid():
    with pytest.raises(ValueError):
        parse_decimal("not-a-number")


# --- producttype.reference (euro decimal string) -> BIGINT cents ------------


@pytest.mark.parametrize(
    "reference, expected_cents",
    [
        ("5.95", 595),  # Salade Cesar C&G (code 1001) BUY price from the Excel
        ("1.45", 145),
        ("1.8", 180),
        ("0,06", 6),  # comma-decimal path
        ("10", 1000),
        ("2.671", 267),  # rounds half-up to nearest cent
        ("2.675", 268),
        ("", None),
        (None, None),
    ],
)
def test_euros_to_minor_units(reference, expected_cents):
    assert euros_to_minor_units(reference) == expected_cents


# --- refund flag ------------------------------------------------------------


@pytest.mark.parametrize(
    "statuses, expected",
    [
        (None, False),
        ([], False),
        ([{"status": "NONE"}], False),
        ([{"status": "PROCESSING"}], False),
        ([{"status": "REFUNDED"}], True),
        ([{"status": "refunded"}], True),  # case-insensitive
        ([{"status": "PARTIALLYREFUNDED"}], True),  # contains 'refunded'
        ([{"status": "NONE"}, {"status": "REFUNDED"}], True),  # any-match
        ([{"foo": "bar"}], False),  # missing status key
    ],
)
def test_is_refunded(statuses, expected):
    assert is_refunded(statuses) is expected


# --- VAT normalisation ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (6.0, Decimal("0.06")),
        (21, Decimal("0.21")),
        (0.06, Decimal("0.06")),  # already a fraction, passthrough
        ("6", Decimal("0.06")),
        (None, None),
    ],
)
def test_normalize_vat_fraction(raw, expected):
    assert normalize_vat_fraction(raw) == expected


# --- discount helpers -------------------------------------------------------


def test_sum_discount_paid():
    discounts = [{"paidAmount": 50, "provider": "FrigoLoco"}, {"paidAmount": 25, "provider": "X"}]
    assert sum_discount_paid(discounts) == Decimal("0.75")
    assert sum_discount_paid(None) == Decimal("0")


def test_first_discount_provider():
    assert first_discount_provider([{"provider": "FrigoLoco"}, {"provider": "X"}]) == "FrigoLoco"
    assert first_discount_provider([{"paidAmount": 1}]) is None
    assert first_discount_provider(None) is None


# --- response model parsing (recorded inline fixtures) ----------------------


def test_purchase_result_parsing_and_extra_allow():
    payload = {
        "from": "2026-06-26T00:00:00Z",
        "to": "2026-06-28T00:00:00Z",
        "merchantName": "frigoloco",
        "unexpectedTopLevel": "kept",  # extra='allow'
        "fridges": {
            "if-0001120": {
                "name": "if-0001120",
                "friendlyName": "HQ Fridge",
                "facility": "HQ",
                "purchases": [
                    {
                        "id": "abc-123",
                        "purchaseDate": "2026-06-27T10:15:00Z",
                        "amount": 350,
                        "products": [
                            {
                                "tagId": "TAG1",
                                "productCode": "1001",
                                "price": 350,
                                "vat": 6.0,
                                "refundStatus": [{"status": "REFUNDED"}],
                                "discounts": [{"paidAmount": 50, "provider": "FrigoLoco"}],
                            }
                        ],
                    }
                ],
            }
        },
    }
    result = PurchaseResult.model_validate(payload)
    fridge = result.fridges["if-0001120"]
    assert fridge.friendlyName == "HQ Fridge"
    product = fridge.purchases[0].products[0]
    assert product.tagId == "TAG1"
    assert minor_units_to_euros(product.price) == Decimal("3.50")
    assert is_refunded(product.refundStatus) is True
    assert result.from_ == datetime.datetime(2026, 6, 26, tzinfo=datetime.timezone.utc)


def test_restock_result_parsing_actions():
    payload = {
        "from": "2026-06-26T00:00:00Z",
        "to": "2026-06-28T00:00:00Z",
        "sessions": {
            "sess-1": {
                "endDate": "2026-06-27T09:00:00Z",
                "fridge": {"name": "if-0001120", "friendlyName": "HQ Fridge"},
                "tags": [
                    {"tagId": "T1", "productCode": "1001", "status": "VALID", "action": "ADDED"},
                    {"tagId": "T2", "productCode": "1001", "status": "VALID", "action": "UNCHANGED"},
                    {"tagId": "T3", "productCode": None, "status": "UNRECOGNISED", "action": "ADDED"},
                ],
            }
        },
    }
    result = RestockResult.model_validate(payload)
    tags = result.sessions["sess-1"].tags
    assert [t.action for t in tags] == ["ADDED", "UNCHANGED", "ADDED"]
    assert result.sessions["sess-1"].fridge.name == "if-0001120"


# --- pure job helpers -------------------------------------------------------


def test_resolve_fridge_by_both_name_and_friendly_name():
    from cron.jobs._base import resolve_fridge

    index = {"if-0001120": 7, "HQ Fridge": 7, "if-0002": 9}
    assert resolve_fridge(index, "if-0001120") == 7
    assert resolve_fridge(index, None, "HQ Fridge") == 7  # resolves by friendlyName
    assert resolve_fridge(index, "unknown") is None


def test_backfill_chunks_are_seven_day_windows():
    from cron.jobs.backfill import _chunks

    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2024, 2, 1, tzinfo=datetime.timezone.utc)
    windows = list(_chunks(start, end))
    assert windows[0] == (start, start + datetime.timedelta(days=7))
    assert windows[-1][1] == end  # last window clamps to `to`
    assert all((b - a) <= datetime.timedelta(days=7) for a, b in windows)
    assert len(windows) == 5


def test_effective_product_code_stub_rules():
    from cron.jobs._base import UNKNOWN_PRODUCT_CODE, effective_product_code

    # A payload code always wins (stubbed later if unknown to the catalogue).
    assert effective_product_code("1001", "TAG1", None) == "1001"
    assert effective_product_code("1001", None, None) == "1001"
    # No code but a tag identity -> shared UNKNOWN stub (event is kept).
    assert effective_product_code(None, "TAG1", None) == UNKNOWN_PRODUCT_CODE
    assert effective_product_code(None, None, "EPC1") == UNKNOWN_PRODUCT_CODE
    assert effective_product_code("", "TAG1", None) == UNKNOWN_PRODUCT_CODE
    # No code AND no tag identity -> None (row skipped, nothing to key on).
    assert effective_product_code(None, None, None) is None
    assert effective_product_code("", None, "") is None


# --- partition maintenance job (residual finding #4) ------------------------


def test_scheduler_registers_monthly_partition_maintenance():
    """The partition-maintenance job fires on the 1st of each month at 01:00."""
    from cron.scheduler import _jobs

    job = next((j for j in _jobs() if j.id == "partition_maintenance"), None)
    assert job is not None, "partition_maintenance job not registered"
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["day"] == "1"
    assert fields["hour"] == "1"
    assert fields["minute"] == "0"


def test_partition_maintenance_run_delegates_to_backend(monkeypatch):
    """The cron ``run()`` wrapper delegates to the backend domain function."""
    from cron.jobs import partition_maintenance

    called = {}

    def _fake_run():
        called["hit"] = True
        return "OUTCOME"

    monkeypatch.setattr(partition_maintenance, "run_partition_maintenance", _fake_run)
    result = partition_maintenance.run()
    assert called.get("hit") is True
    assert result == "OUTCOME"
