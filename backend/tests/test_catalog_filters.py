"""Product / supplier list filters and category ordering plus stock audit user."""

from __future__ import annotations

from sqlalchemy import func, select

from app.husky.sync import UNCATEGORISED_NAME, category_display_order
from app.models.master import Category
from tests import TEST_ADMIN_USER
from tests.test_ops_routers import (
    PREFIX,
    TAG,
    _category_ids,
    _create_product,
    _create_supplier,
    ctx,  # noqa: F401 - pytest fixture
)


def _ensure_uncategorised_category(session) -> None:
    """The catalogue sync creates this row lazily, so a fresh database may not have it yet."""
    existing_id = session.scalar(select(Category.id).where(Category.name == UNCATEGORISED_NAME))
    if existing_id is not None:
        return
    highest_print_order = session.scalar(select(func.max(Category.dispatch_print_order)))
    session.add(
        Category(
            name=UNCATEGORISED_NAME,
            display_order=category_display_order(UNCATEGORISED_NAME),
            dispatch_print_order=highest_print_order + 1,
        )
    )
    session.flush()


def test_products_filter_by_supplier_and_category_with_supplier_name(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    supplier_a = _create_supplier(ctx.client, f"{TAG}FilterSupA")
    supplier_b = _create_supplier(ctx.client, f"{TAG}FilterSupB")
    _create_product(
        ctx.client,
        code=f"{TAG}FLT-a1",
        category_id=cats["normal"],
        supplier_id=supplier_a,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}FLT-a2",
        category_id=cats["drinks"],
        supplier_id=supplier_a,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}FLT-b1",
        category_id=cats["normal"],
        supplier_id=supplier_b,
    )

    by_supplier = ctx.client.get(
        f"{PREFIX}/products",
        params={"supplier_id": supplier_a},
    ).json()
    assert by_supplier["total"] == 2
    assert {item["supplier_name"] for item in by_supplier["items"]} == {f"{TAG}FilterSupA"}

    by_supplier_and_category = ctx.client.get(
        f"{PREFIX}/products",
        params={"supplier_id": supplier_a, "category_id": cats["drinks"]},
    ).json()
    codes = [item["code"] for item in by_supplier_and_category["items"]]
    assert codes == [f"{TAG}FLT-a2"]


def test_products_search_is_case_insensitive_on_code_and_name(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    _create_product(ctx.client, code=f"{TAG}SRCH-Xy", category_id=cats["normal"])

    lower_search = ctx.client.get(
        f"{PREFIX}/products",
        params={"search": f"{TAG}srch-xy".lower()},
    ).json()
    assert [item["code"] for item in lower_search["items"]] == [f"{TAG}SRCH-Xy"]


def test_products_effective_status_filter(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    product_id = _create_product(ctx.client, code=f"{TAG}STAT-1", category_id=cats["normal"])
    ctx.client.put(f"{PREFIX}/products/{product_id}", json={"local_status": "cancelled"})

    cancelled = ctx.client.get(
        f"{PREFIX}/products",
        params={"status": "cancelled", "search": f"{TAG}STAT-1"},
    ).json()
    assert [item["effective_status"] for item in cancelled["items"]] == ["cancelled"]

    active = ctx.client.get(
        f"{PREFIX}/products",
        params={"status": "active", "search": f"{TAG}STAT-1"},
    ).json()
    assert active["total"] == 0

    assert ctx.client.get(f"{PREFIX}/products", params={"status": "bogus"}).status_code == 422


def test_get_product_includes_supplier_name(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    supplier_id = _create_supplier(ctx.client, f"{TAG}NameSup")
    product_id = _create_product(
        ctx.client,
        code=f"{TAG}NAME-1",
        category_id=cats["normal"],
        supplier_id=supplier_id,
    )

    product = ctx.client.get(f"{PREFIX}/products/{product_id}").json()
    assert product["supplier_name"] == f"{TAG}NameSup"


def test_suppliers_filter_by_category_sorted_case_insensitively(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    lower_supplier = _create_supplier(ctx.client, f"{TAG}aCatSup")
    upper_supplier = _create_supplier(ctx.client, f"{TAG}BCatSup")
    other_category_supplier = _create_supplier(ctx.client, f"{TAG}CCatSup")
    _create_product(
        ctx.client,
        code=f"{TAG}CAT-1",
        category_id=cats["normal"],
        supplier_id=upper_supplier,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}CAT-2",
        category_id=cats["normal"],
        supplier_id=lower_supplier,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}CAT-3",
        category_id=cats["drinks"],
        supplier_id=other_category_supplier,
    )

    listing = ctx.client.get(
        f"{PREFIX}/suppliers",
        params={"category_id": cats["normal"], "limit": 500},
    ).json()
    test_supplier_names = [
        item["name"] for item in listing["items"] if item["name"].startswith(TAG)
    ]
    assert test_supplier_names == [f"{TAG}aCatSup", f"{TAG}BCatSup"]


def test_supplier_category_links_list_each_pair_once(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    supplier = _create_supplier(ctx.client, f"{TAG}LinkSup")
    _create_product(
        ctx.client,
        code=f"{TAG}LNK-1",
        category_id=cats["normal"],
        supplier_id=supplier,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}LNK-2",
        category_id=cats["normal"],
        supplier_id=supplier,
    )
    _create_product(
        ctx.client,
        code=f"{TAG}LNK-3",
        category_id=cats["drinks"],
        supplier_id=supplier,
    )

    links = ctx.client.get(f"{PREFIX}/suppliers/category-links").json()
    supplier_category_ids = sorted(
        link["category_id"] for link in links if link["supplier_id"] == supplier
    )
    assert supplier_category_ids == sorted([cats["normal"], cats["drinks"]])


def test_categories_ordered_by_display_order_then_name_uncategorised_last(ctx):  # noqa: F811
    _ensure_uncategorised_category(ctx.session)
    categories = ctx.client.get(f"{PREFIX}/categories").json()

    sort_keys = [(item["display_order"], item["name"]) for item in categories]
    assert sort_keys == sorted(sort_keys)
    assert categories[-1]["name"] == UNCATEGORISED_NAME


def test_stock_adjustment_records_current_user(ctx):  # noqa: F811
    cats = _category_ids(ctx.session)
    product_id = _create_product(ctx.client, code=f"{TAG}AUDIT-1", category_id=cats["normal"])

    movement = ctx.client.post(
        f"{PREFIX}/stock/adjustments",
        json={"product_id": product_id, "qty": 3, "reason": f"{TAG}audit"},
    ).json()
    assert movement["created_by"] == TEST_ADMIN_USER.id
