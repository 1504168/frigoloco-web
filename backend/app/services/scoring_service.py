"""Product scoring engine - legacy parity implementation of R2.

    score = w_pct * (sold / added)
          + w_margin * ((sell_ex_vat - buy) / sell_ex_vat)
          + w_review * ((pos - neg) / (pos + neg))

Weights come from the ``scoring_weights`` settings row (legacy 0.62 / 0.33 / 0.05).
Trailing-365-day window ending ``as_of``. ``added`` excludes UNRECOGNISED tags.
A review with ``rating == 1`` is positive. Components that are undefined (no
added, no reviews, zero ex-VAT price) are stored NULL and contribute 0 to the
weighted total.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.master import Product, Setting
from app.models.planning import ProductScore
from app.services.stock_service import record_audit

_WINDOW_DAYS = 365
_FOUR_PLACES = Decimal("0.0001")

_DEFAULT_WEIGHTS = {
    "pct_sold": Decimal("0.62"),
    "margin": Decimal("0.33"),
    "review": Decimal("0.05"),
}


@dataclass(frozen=True)
class ScoringWeights:
    pct_sold: Decimal
    margin: Decimal
    review: Decimal


@dataclass(frozen=True)
class _ProductScoreComponents:
    product_id: int
    pct_sold: Decimal | None
    margin: Decimal | None
    review: Decimal | None
    final_score: Decimal
    sample_size: int


def _load_weights(session: Session) -> ScoringWeights:
    setting = session.get(Setting, "scoring_weights")
    raw = setting.value if setting and isinstance(setting.value, dict) else {}
    return ScoringWeights(
        pct_sold=Decimal(str(raw.get("pct_sold", _DEFAULT_WEIGHTS["pct_sold"]))),
        margin=Decimal(str(raw.get("margin", _DEFAULT_WEIGHTS["margin"]))),
        review=Decimal(str(raw.get("review", _DEFAULT_WEIGHTS["review"]))),
    )


def _counts(query: str, params: dict, session: Session) -> dict[int, tuple]:
    rows = session.execute(text(query), params).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _compute_components(
    product: Product,
    sold: int,
    added: int,
    positive: int,
    negative: int,
    weights: ScoringWeights,
) -> _ProductScoreComponents:
    pct_sold = Decimal(sold) / Decimal(added) if added > 0 else None

    sell_ex_vat = (
        product.sales_price / (Decimal("1") + product.vat_rate)
        if product.vat_rate is not None
        else product.sales_price
    )
    margin = (
        (sell_ex_vat - product.purchase_price) / sell_ex_vat
        if sell_ex_vat and sell_ex_vat > 0
        else None
    )

    total_reviews = positive + negative
    review = (
        Decimal(positive - negative) / Decimal(total_reviews)
        if total_reviews > 0
        else None
    )

    final = (
        weights.pct_sold * (pct_sold or Decimal("0"))
        + weights.margin * (margin or Decimal("0"))
        + weights.review * (review or Decimal("0"))
    )

    return _ProductScoreComponents(
        product_id=product.id,
        pct_sold=None if pct_sold is None else pct_sold.quantize(_FOUR_PLACES),
        margin=None if margin is None else margin.quantize(_FOUR_PLACES),
        review=None if review is None else review.quantize(_FOUR_PLACES),
        final_score=final.quantize(_FOUR_PLACES),
        sample_size=added,
    )


def recompute_scores(
    *, as_of: datetime.date, user_id: int | None, session: Session
) -> int:
    """Recompute and upsert ``product_scores`` for ``period_end = as_of``.

    Returns the number of products scored. Products with no sales, additions or
    reviews in the window are skipped.
    """
    window_start = as_of - datetime.timedelta(days=_WINDOW_DAYS)
    weights = _load_weights(session)
    params = {"start": window_start, "end": as_of}

    sold_map = _counts(
        "SELECT product_id, count(*) FROM sales_events "
        "WHERE is_refunded = false AND sold_at >= :start AND sold_at < :end "
        "GROUP BY product_id",
        params,
        session,
    )
    added_map = _counts(
        "SELECT product_id, count(*) FROM restock_events "
        "WHERE action = 'added' AND tag_status <> 'unrecognised' "
        "AND occurred_at >= :start AND occurred_at < :end GROUP BY product_id",
        params,
        session,
    )
    review_map = _counts(
        "SELECT product_id, count(*) FILTER (WHERE rating = 1), "
        "count(*) FILTER (WHERE rating <> 1) FROM product_reviews "
        "WHERE reviewed_at >= :start AND reviewed_at < :end GROUP BY product_id",
        params,
        session,
    )

    product_ids = set(sold_map) | set(added_map) | set(review_map)
    if not product_ids:
        session.commit()
        return 0

    products = {
        product.id: product
        for product in session.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        .scalars()
        .all()
    }

    scored = 0
    for product_id in product_ids:
        product = products.get(product_id)
        if product is None:  # sales for a product not in the catalogue
            continue
        sold = int(sold_map.get(product_id, (0,))[0])
        added = int(added_map.get(product_id, (0,))[0])
        positive, negative = review_map.get(product_id, (0, 0))
        components = _compute_components(
            product, sold, added, int(positive), int(negative), weights
        )
        session.execute(
            pg_insert(ProductScore)
            .values(
                product_id=components.product_id,
                period_end=as_of,
                pct_sold=components.pct_sold,
                review_score=components.review,
                margin_score=components.margin,
                final_score=components.final_score,
                sample_size=components.sample_size,
            )
            .on_conflict_do_update(
                index_elements=["product_id", "period_end"],
                set_={
                    "pct_sold": components.pct_sold,
                    "review_score": components.review,
                    "margin_score": components.margin,
                    "final_score": components.final_score,
                    "sample_size": components.sample_size,
                    "computed_at": text("now()"),
                },
            )
        )
        scored += 1

    record_audit(
        session,
        action="scoring.recompute",
        entity="product_scores",
        entity_id=None,
        after={"period_end": as_of.isoformat(), "products_scored": scored},
        user_id=user_id,
    )
    session.commit()
    return scored


def list_scores(
    *,
    period_end: datetime.date | None,
    product_id: int | None,
    limit: int,
    offset: int,
    session: Session,
) -> tuple[list[ProductScore], int]:
    resolved_period = period_end
    if resolved_period is None:
        resolved_period = session.execute(
            select(ProductScore.period_end).order_by(ProductScore.period_end.desc()).limit(1)
        ).scalar()

    stmt = select(ProductScore)
    count_stmt = select(text("count(*)")).select_from(ProductScore)
    if resolved_period is not None:
        stmt = stmt.where(ProductScore.period_end == resolved_period)
        count_stmt = count_stmt.where(ProductScore.period_end == resolved_period)
    if product_id is not None:
        stmt = stmt.where(ProductScore.product_id == product_id)
        count_stmt = count_stmt.where(ProductScore.product_id == product_id)

    total = session.execute(count_stmt).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(ProductScore.final_score.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    return rows, int(total)
