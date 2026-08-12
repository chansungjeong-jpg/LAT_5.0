from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DailyMAReactionInputs:
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


def score_daily_reaction(
    daily: pd.DataFrame, as_of: pd.Timestamp
) -> DailyMAReaction:
    DailyMAReactionInputs(daily=daily, as_of=as_of)
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in daily.columns]
    if missing:
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            unknown_fields=missing,
        )

    completed = daily.loc[daily.index <= as_of]
    close = completed["close"]
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
