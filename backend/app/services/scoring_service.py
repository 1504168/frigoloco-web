"""Product scoring engine - legacy parity implementation of R2.

    score = w_pct * (sold / added)
          + w_margin * ((sell_ex_vat - buy) / sell_ex_vat)
          + w_review * ((pos - neg) / (pos + neg))

Weights come from the ``scoring_weights`` settings row (legacy 0.62 / 0.33 / 0.05).
Trailing window of 90, 180 or 365 days ending ``as_of``; each window is stored
as its own set of ``product_scores`` rows. ``added`` excludes UNRECOGNISED tags.
A review with ``rating == 1`` is positive. Components that are undefined (no
added, no reviews, zero ex-VAT price) are stored NULL and contribute 0 to the
weighted total.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.models.master import Product, Setting
from app.models.planning import ProductScore
from app.services.stock_service import record_audit


class ScoreWindowDays(IntEnum):
    LAST_90_DAYS = 90
    LAST_180_DAYS = 180
    LAST_365_DAYS = 365


SCORE_WINDOW_OPTIONS = tuple(ScoreWindowDays)
# Default window (legacy parity); menu allocation and the ops score map always read it.
YEARLY_SCORE_WINDOW_DAYS = ScoreWindowDays.LAST_365_DAYS
_FOUR_PLACES = Decimal("0.0001")
# Postgres advisory lock id per window: this base plus window_days.
_RECOMPUTE_LOCK_KEY_BASE = 7_340_000

_DEFAULT_WEIGHTS = {
    "pct_sold": Decimal("0.62"),
    "margin": Decimal("0.33"),
    "review": Decimal("0.05"),
}

# Slide 18: products with too few sales in the window get the average global
# score as a placeholder until real data accumulates. Threshold is on sales
# count and is overridable via the ``new_product_sales_threshold`` setting.
_DEFAULT_NEW_PRODUCT_SALES_THRESHOLD = 250


@dataclass(frozen=True)
class ScoringWeights:
    pct_sold: Decimal
    margin: Decimal
    review: Decimal


@dataclass(frozen=True)
class _ProductActivity:
    sold: int
    added: int
    positive_reviews: int
    negative_reviews: int


@dataclass(frozen=True)
class _ProductScoreComponents:
    product_id: int
    pct_sold: Decimal | None
    margin: Decimal | None
    review: Decimal | None
    final_score: Decimal
    sample_size: int
    sold_qty: int
    positive_reviews: int
    negative_reviews: int


def load_weights(session: Session) -> ScoringWeights:
    setting = session.get(Setting, "scoring_weights")
    raw = setting.value if setting and isinstance(setting.value, dict) else {}
    return ScoringWeights(
        pct_sold=Decimal(str(raw.get("pct_sold", _DEFAULT_WEIGHTS["pct_sold"]))),
        margin=Decimal(str(raw.get("margin", _DEFAULT_WEIGHTS["margin"]))),
        review=Decimal(str(raw.get("review", _DEFAULT_WEIGHTS["review"]))),
    )


def recompute_scores(
    *,
    as_of: datetime.date,
    window_days: int,
    user_id: int | None,
    session: Session,
) -> int:
    """Recompute and upsert ``product_scores`` for ``(as_of, window_days)``.

    Returns the number of products scored. Products with no sales, additions or
    reviews in the window are skipped.
    """
    window_start = as_of - datetime.timedelta(days=window_days)
    activity_by_product = _load_product_activity(window_start, as_of, session)
    weights = load_weights(session)
    active_product_ids = list(activity_by_product)
    products = session.execute(
        select(Product).where(Product.id.in_(active_product_ids))
    ).scalars().all()

    computed: list[_ProductScoreComponents] = []
    for product in products:
        activity = activity_by_product[product.id]
        computed.append(_compute_components(product, activity, weights))

    new_product_threshold = _load_new_product_threshold(session)
    baseline = _average_established_score(computed, new_product_threshold)
    score_rows: list[dict] = []
    for components in computed:
        uses_baseline = baseline is not None and components.sold_qty <= new_product_threshold
        final_score = baseline if uses_baseline else components.final_score
        score_rows.append(
            _build_score_row(
                components,
                final_score=final_score,
                uses_baseline=uses_baseline,
                period_end=as_of,
                window_days=window_days,
            )
        )
    _replace_period_scores(score_rows, period_end=as_of, window_days=window_days, session=session)

    record_audit(
        session,
        action="scoring.recompute",
        entity="product_scores",
        entity_id=None,
        after={
            "period_end": as_of.isoformat(),
            "window_days": window_days,
            "products_scored": len(computed),
        },
        user_id=user_id,
    )
    session.commit()
    return len(computed)


def latest_score_period(session: Session, window_days: int) -> datetime.date | None:
    """Newest ``period_end`` stored for ``window_days``; None when never computed."""
    return session.execute(
        select(ProductScore.period_end)
        .where(ProductScore.window_days == window_days)
        .order_by(ProductScore.period_end.desc())
        .limit(1)
    ).scalar()


def load_latest_final_scores(
    session: Session,
    window_days: int = YEARLY_SCORE_WINDOW_DAYS,
) -> dict[int, Decimal]:
    """Product id -> final score of the newest stored period for ``window_days``."""
    period_end = latest_score_period(session, window_days)
    if period_end is None:
        return {}
    score_rows = session.execute(
        select(ProductScore.product_id, ProductScore.final_score).where(
            ProductScore.window_days == window_days,
            ProductScore.period_end == period_end,
        )
    ).all()
    return dict(score_rows)


def list_scores(
    *,
    period_end: datetime.date | None,
    window_days: int,
    product_id: int | None,
    limit: int,
    offset: int,
    session: Session,
) -> tuple[list[ProductScore], int]:
    resolved_period = period_end or latest_score_period(session, window_days)
    filters = [
        ProductScore.window_days == window_days,
        ProductScore.period_end == resolved_period,
    ]
    if product_id is not None:
        filters.append(ProductScore.product_id == product_id)

    total = session.execute(
        select(func.count()).select_from(ProductScore).where(*filters)
    ).scalar_one()
    rows = list(
        session.execute(
            select(ProductScore)
            .where(*filters)
            .order_by(ProductScore.final_score.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return rows, total


def _load_new_product_threshold(session: Session) -> int:
    setting = session.get(Setting, "new_product_sales_threshold")
    value = setting.value if setting is not None else None
    try:
        return int(value)  # accepts JSON number or numeric string
    except (TypeError, ValueError):
        return _DEFAULT_NEW_PRODUCT_SALES_THRESHOLD


def _load_product_activity(
    window_start: datetime.date,
    window_end: datetime.date,
    session: Session,
) -> dict[int, _ProductActivity]:
    params = {"start": window_start, "end": window_end}
    sold_by_product = _count_by_product(
        "SELECT product_id, count(*) FROM sales_events "
        "WHERE is_refunded = false AND sold_at >= :start AND sold_at < :end "
        "GROUP BY product_id",
        params,
        session,
    )
    added_by_product = _count_by_product(
        "SELECT product_id, count(*) FROM restock_events "
        "WHERE action = 'added' AND tag_status <> 'unrecognised' "
        "AND occurred_at >= :start AND occurred_at < :end GROUP BY product_id",
        params,
        session,
    )
    positive_by_product = _count_by_product(
        "SELECT product_id, count(*) FROM product_reviews "
        "WHERE rating = 1 AND reviewed_at >= :start AND reviewed_at < :end "
        "GROUP BY product_id",
        params,
        session,
    )
    negative_by_product = _count_by_product(
        "SELECT product_id, count(*) FROM product_reviews "
        "WHERE rating <> 1 AND reviewed_at >= :start AND reviewed_at < :end "
        "GROUP BY product_id",
        params,
        session,
    )
    active_product_ids = (
        set(sold_by_product)
        | set(added_by_product)
        | set(positive_by_product)
        | set(negative_by_product)
    )
    activity_by_product: dict[int, _ProductActivity] = {}
    for product_id in active_product_ids:
        activity_by_product[product_id] = _ProductActivity(
            sold=sold_by_product.get(product_id, 0),
            added=added_by_product.get(product_id, 0),
            positive_reviews=positive_by_product.get(product_id, 0),
            negative_reviews=negative_by_product.get(product_id, 0),
        )
    return activity_by_product


def _count_by_product(query: str, params: dict, session: Session) -> dict[int, int]:
    count_rows = session.execute(text(query), params).all()
    return dict(count_rows)


def _compute_components(
    product: Product,
    activity: _ProductActivity,
    weights: ScoringWeights,
) -> _ProductScoreComponents:
    pct_sold = (
        Decimal(activity.sold) / Decimal(activity.added) if activity.added > 0 else None
    )

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

    total_reviews = activity.positive_reviews + activity.negative_reviews
    review = (
        Decimal(activity.positive_reviews - activity.negative_reviews) / Decimal(total_reviews)
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
        sample_size=activity.added,
        sold_qty=activity.sold,
        positive_reviews=activity.positive_reviews,
        negative_reviews=activity.negative_reviews,
    )


def _average_established_score(
    computed: list[_ProductScoreComponents],
    threshold: int,
) -> Decimal | None:
    """Average final score of products whose sales exceed ``threshold``.

    None when no product clears the threshold, so every product keeps its own score.
    """
    established_scores = [
        components.final_score for components in computed if components.sold_qty > threshold
    ]
    if not established_scores:
        return None
    average = sum(established_scores, Decimal("0")) / Decimal(len(established_scores))
    return average.quantize(_FOUR_PLACES)


def _build_score_row(
    components: _ProductScoreComponents,
    *,
    final_score: Decimal,
    uses_baseline: bool,
    period_end: datetime.date,
    window_days: int,
) -> dict:
    return {
        "product_id": components.product_id,
        "period_end": period_end,
        "window_days": window_days,
        "pct_sold": components.pct_sold,
        "review_score": components.review,
        "margin_score": components.margin,
        "final_score": final_score,
        "sample_size": components.sample_size,
        "sold_qty": components.sold_qty,
        "positive_reviews": components.positive_reviews,
        "negative_reviews": components.negative_reviews,
        "uses_new_product_baseline": uses_baseline,
    }


def _replace_period_scores(
    score_rows: list[dict],
    *,
    period_end: datetime.date,
    window_days: int,
    session: Session,
) -> None:
    # Two recomputes of one window (double click, or the nightly job) would both
    # delete and then collide on insert; the lock makes the second wait its turn.
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _RECOMPUTE_LOCK_KEY_BASE + window_days},
    )
    # Replacing the whole period drops products that left the window since an
    # earlier run on the same day.
    session.execute(
        delete(ProductScore).where(
            ProductScore.period_end == period_end,
            ProductScore.window_days == window_days,
        )
    )
    if score_rows:
        session.execute(insert(ProductScore), score_rows)
