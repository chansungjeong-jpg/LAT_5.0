from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd


_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class DailyMAReactionInputs:
    """Completed daily bars and the beginning of the evaluation date."""

    daily: pd.DataFrame
    as_of: pd.Timestamp


@dataclass(frozen=True)
class DailyMAReaction:
    reaction: str
    base_score: int
    quality_bonus: int
    total_score: int
    sma5: float | None
    sma20: float | None
    sma60: float | None
    status: str
    reasons: tuple[str, ...]
    unknown_fields: tuple[str, ...]


def _sma(close: pd.Series, window: int) -> float | None:
    values = close.tail(window)
    if len(values) < window or values.isna().any():
        return None
    return float(values.mean())


def _unknown_result(
    *,
    sma5: float | None,
    sma20: float | None,
    sma60: float | None,
    unknown_fields: list[str],
) -> DailyMAReaction:
    return DailyMAReaction(
        reaction="UNKNOWN",
        base_score=0,
        quality_bonus=0,
        total_score=0,
        sma5=sma5,
        sma20=sma20,
        sma60=sma60,
        status="UNKNOWN",
        reasons=("REQUIRED_DATA_UNKNOWN",),
        unknown_fields=tuple(unknown_fields),
    )


def _completed_bars(
    daily: pd.DataFrame, as_of: pd.Timestamp
) -> tuple[pd.DataFrame | None, tuple[str, ...]]:
    if not isinstance(daily.index, pd.DatetimeIndex):
        return None, ("datetime_index",)
    if daily.index.hasnans or not daily.index.is_monotonic_increasing:
        return None, ("datetime_index",)

    try:
        evaluation_date = pd.Timestamp(as_of)
        if pd.isna(evaluation_date):
            return None, ("as_of",)
        completed = daily.loc[
            daily.index.normalize() < evaluation_date.normalize()
        ]
        if completed.index.normalize().duplicated().any():
            return None, ("datetime_index",)
    except (TypeError, ValueError):
        return None, ("datetime_index",)
    return completed, ()


def _validated_ohlcv(
    completed: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    validated = pd.DataFrame(index=completed.index)
    invalid_fields: list[str] = []
    for field in _REQUIRED_COLUMNS:
        values = pd.to_numeric(completed[field], errors="coerce")
        finite = values.map(
            lambda value: pd.notna(value) and isfinite(float(value))
        )
        if not bool(finite.all()):
            invalid_fields.append(field)
        validated[field] = values
    return validated, tuple(invalid_fields)


def score_daily_ma_reaction(
    daily: pd.DataFrame, as_of: pd.Timestamp
) -> DailyMAReaction:
    DailyMAReactionInputs(daily=daily, as_of=as_of)
    missing = [column for column in _REQUIRED_COLUMNS if column not in daily.columns]
    if missing:
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            unknown_fields=missing,
        )

    completed, index_unknown = _completed_bars(daily, as_of)
    if index_unknown:
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            unknown_fields=list(index_unknown),
        )

    assert completed is not None
    validated, invalid_fields = _validated_ohlcv(completed)
    if invalid_fields:
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            unknown_fields=list(invalid_fields),
        )

    close = validated["close"]
    sma5 = _sma(close, 5)
    sma20 = _sma(close, 20)
    sma60 = _sma(close, 60)
    unknown_fields = [
        name
        for name, value in (("SMA5", sma5), ("SMA20", sma20), ("SMA60", sma60))
        if value is None
    ]
    if unknown_fields:
        return _unknown_result(
            sma5=sma5,
            sma20=sma20,
            sma60=sma60,
            unknown_fields=unknown_fields,
        )

    return DailyMAReaction(
        reaction="NONE",
        base_score=0,
        quality_bonus=0,
        total_score=0,
        sma5=sma5,
        sma20=sma20,
        sma60=sma60,
        status="KNOWN",
        reasons=(),
        unknown_fields=(),
    )


score_daily_reaction = score_daily_ma_reaction


__all__ = [
    "DailyMAReactionInputs",
    "DailyMAReaction",
    "score_daily_ma_reaction",
    "score_daily_reaction",
]
