"""Registry of forecast methods, keyed by the code stored in ``forecast_runs.model``."""

from __future__ import annotations

from app.schemas.masters import api_error
from app.services.forecast.strategies.base import ForecastStrategy, SalesWindow
from app.services.forecast.strategies.last_year_3m import LastYear3Months
from app.services.forecast.strategies.last_year_3w import LastYear3Weeks
from app.services.forecast.strategies.moving_average_3m import MovingAverage3Months
from app.services.forecast.strategies.moving_average_3w import MovingAverage3Weeks

__all__ = [
    "DEFAULT_STRATEGY_CODE",
    "FORECAST_STRATEGIES",
    "ForecastStrategy",
    "SalesWindow",
    "get_strategy",
]

DEFAULT_STRATEGY_CODE = MovingAverage3Weeks.code

# Display order of the method picker.
FORECAST_STRATEGIES: dict[str, ForecastStrategy] = {
    strategy.code: strategy
    for strategy in (
        MovingAverage3Weeks(),
        MovingAverage3Months(),
        LastYear3Weeks(),
        LastYear3Months(),
    )
}


def get_strategy(code: str) -> ForecastStrategy:
    """The strategy for ``code``; 422 for an unknown method."""
    if code not in FORECAST_STRATEGIES:
        raise api_error(
            422,
            "validation_error",
            "Unknown forecast model",
            {"model": code, "allowed": list(FORECAST_STRATEGIES)},
        )
    return FORECAST_STRATEGIES[code]
