"""Stock balances listing: category / supplier / search filters and ordering."""

from __future__ import annotations

from tests.test_ops_routers import (
    PREFIX,
    TAG,
    _category_ids,
    _create_product,
    _create_supplier,
    ctx,  # noqa: F401 - pytest fixture
)

BALANCES_URL = f"{PREFIX}/stock/balances"
MAX_PAGE_SIZE = 500


def _seed_balances_products(ctx) -> dict[str, int]:  # noqa: F811
    cats = _category_ids(ctx.session)
    supplier_b = _create_supplier(ctx.client, f"{TAG}StkSupB")
    supplier_a = _create_supplier(ctx.client, f"{TAG}stkSupA")
    _create_product(
        ctx.client,
        code=f"{TAG}STK-n1",
        category_id=cats["normal"],
        supplier_id=supplier_b,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}STK-n2",
        category_id=cats["normal"],
        supplier_id=supplier_a,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}STK-d1",
        category_id=cats["drinks"],
        supplier_id=supplier_a,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}STK-n3",
        category_id=cats["normal"],
    )
    return {
        "normal": cats["normal"],
        "drinks": cats["drinks"],
        "supplier_a": supplier_a,
        "supplier_b": supplier_b,
    }


def _balance_codes(ctx, params: dict[str, object]) -> list[str]:  # noqa: F811
    listing = ctx.client.get(BALANCES_URL, params={**params, "limit": MAX_PAGE_SIZE})
    assert listing.status_code == 200, listing.text
    return [item["product_code"] for item in listing.json()["items"]]


def test_balances_filter_by_category_and_supplier(ctx):  # noqa: F811
    seeded = _seed_balances_products(ctx)

    by_category = _balance_codes(ctx, {"category_id": seeded["drinks"], "search": f"{TAG}STK"})
    assert by_category == [f"{TAG}STK-d1"]

    by_supplier = _balance_codes(ctx, {"supplier_id": seeded["supplier_a"]})
    assert sorted(by_supplier) == [f"{TAG}STK-d1", f"{TAG}STK-n2"]

    by_both = _balance_codes(
        ctx,
        {"category_id": seeded["normal"], "supplier_id": seeded["supplier_a"]},
    )
    assert by_both == [f"{TAG}STK-n2"]


def test_balances_search_is_case_insensitive_contains(ctx):  # noqa: F811
    _seed_balances_products(ctx)

    codes = _balance_codes(ctx, {"search": "zztest-stk-N"})
    assert sorted(codes) == [f"{TAG}STK-n1", f"{TAG}STK-n2", f"{TAG}STK-n3"]


def test_balances_include_category_and_supplier_sorted_by_supplier(ctx):  # noqa: F811
    seeded = _seed_balances_products(ctx)

    listing = ctx.client.get(
        BALANCES_URL,
        params={"category_id": seeded["normal"], "search": f"{TAG}STK"},
    ).json()
    rows = [
        (item["product_code"], item["supplier_name"])
        for item in listing["items"]
    ]
    assert rows == [
        (f"{TAG}STK-n2", f"{TAG}stkSupA"),
        (f"{TAG}STK-n1", f"{TAG}StkSupB"),
        (f"{TAG}STK-n3", None),
    ]
    assert listing["total"] == 3
    assert {item["category_id"] for item in listing["items"]} == {seeded["normal"]}
    assert all(item["category_name"] for item in listing["items"])
