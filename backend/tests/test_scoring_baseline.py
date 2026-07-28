"""Unit tests for the new-product baseline scoring rule (slide 18).

The full recompute is a global pass over the live DB (hard to assert a specific
value hermetically), so the baseline math is extracted into a pure helper and
tested directly here. The application rule (sales <= threshold -> inherit the
baseline) is exercised through the helper's output.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.scoring_service import (
    _ProductScoreComponents,
    _average_established_score,
)


def _components(product_id: int, final_score: str) -> _ProductScoreComponents:
    return _ProductScoreComponents(
        product_id=product_id,
        pct_sold=None,
        margin=None,
        review=None,
        final_score=Decimal(final_score),
        sample_size=0,
    )


def test_baseline_is_average_of_established_products():
    # Two established products (sold above threshold) -> baseline is their mean.
    computed = [
        (_components(1, "0.8000"), 300),  # established
        (_components(2, "0.4000"), 400),  # established
        (_components(3, "0.9900"), 5),    # new: score ignored for the baseline
    ]
    assert _average_established_score(computed, threshold=250) == Decimal("0.6000")


def test_no_established_products_yields_no_baseline():
    # Every product is under the threshold -> None (no override applied).
    computed = [
        (_components(1, "0.8000"), 10),
        (_components(2, "0.4000"), 20),
    ]
    assert _average_established_score(computed, threshold=250) is None


def test_threshold_is_strict_greater_than():
    # Exactly at the threshold counts as NEW (not established).
    computed = [
        (_components(1, "0.5000"), 250),  # == threshold -> new
        (_components(2, "0.7000"), 251),  # > threshold -> established
    ]
    assert _average_established_score(computed, threshold=250) == Decimal("0.7000")
