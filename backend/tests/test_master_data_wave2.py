"""Pure tests (no DB, no network) for supplier schedules, client rules, product tags and
the equipment register."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db import get_db
from app.main import app
from app.models.master import ClientRule, Supplier, SupplierDeliverySchedule
from app.routers import clients as clients_router
from app.routers import suppliers as suppliers_router
from app.schemas.masters import (
    ClientRuleCreate,
    EquipmentCreate,
    FridgeUpdate,
    ProductTagsReplace,
    SupplierUpdate,
    normalize_tag,
)
from app.services.client_rules_service import RuleViolation, match_rule_violations
from app.services.supplier_schedule_service import (
    LOCAL_TIMEZONE,
    NextDelivery,
    days_before_delivery,
    next_delivery_from_schedule,
)

PREFIX = "/api/v1"
MONDAY = 1
WEDNESDAY = 3
FRIDAY = 5
NOON = datetime.time(12, 0)
# 2026-11-12 is a Thursday.
THURSDAY_MORNING = datetime.datetime(2026, 11, 12, 9, 0)
NEXT_MONDAY = datetime.date(2026, 11, 16)
FRIDAY_NOON_BEFORE_NEXT_MONDAY = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=LOCAL_TIMEZONE)

MONDAY_DELIVERY_FRIDAY_CUTOFF = SupplierDeliverySchedule(
    supplier_id=1,
    delivery_weekday=MONDAY,
    cutoff_weekday=FRIDAY,
    cutoff_time=NOON,
)


class _SessionReturningSupplier:
    def get(self, model, primary_key):
        return Supplier(id=primary_key, name="Technicup")


@pytest.fixture()
def api_client():
    app.dependency_overrides[get_db] = _yield_supplier_session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _yield_supplier_session():
    yield _SessionReturningSupplier()


def test_monday_delivery_needs_the_order_by_friday_noon() -> None:
    next_delivery = next_delivery_from_schedule(
        [MONDAY_DELIVERY_FRIDAY_CUTOFF], THURSDAY_MORNING
    )

    assert next_delivery == NextDelivery(
        delivery_date=NEXT_MONDAY,
        order_deadline=FRIDAY_NOON_BEFORE_NEXT_MONDAY,
    )


def test_an_order_after_the_cutoff_moves_to_the_following_week() -> None:
    friday_afternoon = datetime.datetime(2026, 11, 13, 13, 0)

    next_delivery = next_delivery_from_schedule(
        [MONDAY_DELIVERY_FRIDAY_CUTOFF], friday_afternoon
    )

    assert next_delivery is not None
    assert next_delivery.delivery_date == NEXT_MONDAY + datetime.timedelta(days=7)


def test_the_earliest_of_several_delivery_days_wins() -> None:
    wednesday_delivery_monday_cutoff = SupplierDeliverySchedule(
        supplier_id=1,
        delivery_weekday=WEDNESDAY,
        cutoff_weekday=MONDAY,
        cutoff_time=NOON,
    )
    sunday_evening = datetime.datetime(2026, 11, 15, 20, 0)

    next_delivery = next_delivery_from_schedule(
        [MONDAY_DELIVERY_FRIDAY_CUTOFF, wednesday_delivery_monday_cutoff],
        sunday_evening,
    )

    assert next_delivery is not None
    assert next_delivery.delivery_date == datetime.date(2026, 11, 18)


def test_a_utc_order_time_is_compared_in_brussels_time() -> None:
    # 11:30 UTC on Friday is 12:30 in Brussels: the Friday noon cutoff is already gone.
    friday_utc = datetime.datetime(2026, 11, 13, 11, 30, tzinfo=datetime.timezone.utc)

    next_delivery = next_delivery_from_schedule([MONDAY_DELIVERY_FRIDAY_CUTOFF], friday_utc)

    assert next_delivery is not None
    assert next_delivery.delivery_date == datetime.date(2026, 11, 23)


def test_no_schedule_means_no_next_delivery() -> None:
    assert next_delivery_from_schedule([], THURSDAY_MORNING) is None


@pytest.mark.parametrize(
    "delivery_weekday, cutoff_weekday, expected_days",
    [
        (MONDAY, FRIDAY, 3),
        (WEDNESDAY, MONDAY, 2),
        (MONDAY, MONDAY, 0),
    ],
)
def test_days_before_delivery(delivery_weekday, cutoff_weekday, expected_days) -> None:
    assert days_before_delivery(delivery_weekday, cutoff_weekday) == expected_days


def test_client_wide_rule_hits_every_fridge_and_fridge_rule_only_its_fridge() -> None:
    client_wide_no_pork = ClientRule(id=1, client_id=10, fridge_id=None, tag="contains_pork")
    one_fridge_no_alcohol = ClientRule(id=2, client_id=10, fridge_id=101, tag="contains_alcohol")
    other_client_no_nuts = ClientRule(id=3, client_id=20, fridge_id=None, tag="contains_nuts")
    client_id_by_fridge = {101: 10, 102: 10}
    tags_by_product = {
        7: {"contains_pork"},
        8: {"contains_alcohol", "contains_nuts"},
        9: {"vegan"},
    }

    violations = match_rule_violations(
        client_id_by_fridge,
        [client_wide_no_pork, one_fridge_no_alcohol, other_client_no_nuts],
        tags_by_product,
    )

    violation_keys = {(item.fridge_id, item.product_id, item.rule_id) for item in violations}
    assert violation_keys == {(101, 7, 1), (102, 7, 1), (101, 8, 2)}


def test_violations_endpoint_passes_the_ids_to_the_service(monkeypatch, api_client) -> None:
    received_arguments: list[tuple] = []

    def fake_find_rule_violations(session, product_ids, fridge_ids, on_date):
        received_arguments.append((product_ids, fridge_ids, on_date))
        return [RuleViolation(fridge_id=1, product_id=2, rule_id=3, tag="halal", note=None)]

    monkeypatch.setattr(clients_router, "find_rule_violations", fake_find_rule_violations)
    response = api_client.get(
        f"{PREFIX}/clients/rules/violations",
        params={"product_ids": [2, 5], "fridge_ids": [1], "on_date": "2026-11-12"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {"fridge_id": 1, "product_id": 2, "rule_id": 3, "tag": "halal", "note": None}
    ]
    assert received_arguments == [([2, 5], [1], datetime.date(2026, 11, 12))]


def test_next_delivery_endpoint_returns_date_and_deadline(monkeypatch, api_client) -> None:
    monkeypatch.setattr(
        suppliers_router,
        "find_next_supplier_delivery",
        lambda session, supplier_id, ordered_at: NextDelivery(
            delivery_date=NEXT_MONDAY,
            order_deadline=FRIDAY_NOON_BEFORE_NEXT_MONDAY,
        ),
    )

    response = api_client.get(f"{PREFIX}/suppliers/4/next-delivery")

    assert response.status_code == 200
    assert response.json()["delivery_date"] == "2026-11-16"


def test_tags_are_normalized_and_deduplicated() -> None:
    body = ProductTagsReplace(tags=["Contains Pork", "vegan", "contains-pork"])

    assert body.tags == ["contains_pork", "vegan"]


def test_a_tag_with_other_characters_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_tag("sans porc!")


def test_exclude_tag_rule_needs_a_tag() -> None:
    with pytest.raises(ValidationError):
        ClientRuleCreate(rule_type="exclude_tag")


def test_equipment_money_is_stored_in_cents_and_rate_as_fraction() -> None:
    equipment = EquipmentCreate(
        machine_type="Technicup 2",
        equipment_category="coffee",
        machine_code="C.TC2-001",
        ownership="bought",
        purchase_price="3654.00",
        monthly_fee="365",
        financing_years=3,
        financing_rate="0.04",
    )

    stored_fields = equipment.model_dump(by_alias=True)
    assert stored_fields["purchase_price_cents"] == 365400
    assert stored_fields["monthly_fee_cents"] == 36500
    assert stored_fields["financing_rate"] == Decimal("0.04")
    assert stored_fields["equipment_category"] == "coffee"


def test_a_money_field_that_is_not_a_number_is_a_validation_error() -> None:
    with pytest.raises(ValidationError, match="not a euro amount"):
        EquipmentCreate(
            machine_type="Technicup 2",
            equipment_category="coffee",
            machine_code="C.TC2-001",
            ownership="bought",
            purchase_price="abc",
        )


def test_a_partial_update_cannot_null_a_not_null_column() -> None:
    assert FridgeUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        FridgeUpdate(night_delivery_ok=None)
    with pytest.raises(ValidationError):
        SupplierUpdate(payment_terms_end_of_month=None)


def test_a_note_rule_cannot_carry_a_tag() -> None:
    with pytest.raises(ValidationError):
        ClientRuleCreate(rule_type="note", note="likes vegan", tag="vegan")
