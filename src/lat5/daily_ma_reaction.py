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
    rsi14: float | None
    rsi_state: str
    rsi_bonus: int
    rsi_reasons: tuple[str, ...]
    status: str
    reasons: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    quality_components: dict[str, int]
    quality_reasons: tuple[str, ...]
    quality_method: str | None
    five_day_state: str


def _sma(close: pd.Series, window: int) -> float | None:
    values = close.tail(window)
    if len(values) < window or values.isna().any():
        return None
    return float(values.mean())


def _sma_series(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def _atr_series(validated: pd.DataFrame, window: int = 14) -> pd.Series:
    previous_close = validated["close"].shift(1)
    true_range = pd.concat(
        [
            validated["high"] - validated["low"],
            (validated["high"] - previous_close).abs(),
            (validated["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=window, min_periods=window).mean()


def _wilder_rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    """Return Wilder RSI seeded by the first window's simple averages."""
    result = pd.Series(float("nan"), index=close.index, dtype=float)
    if len(close) < window + 1:
        return result

    changes = close.diff()
    gains = changes.clip(lower=0.0)
    losses = (-changes.clip(upper=0.0))
    average_gain = float(gains.iloc[1 : window + 1].mean())
    average_loss = float(losses.iloc[1 : window + 1].mean())

    def _rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0
        return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    result.iloc[window] = _rsi(average_gain, average_loss)
    for position in range(window + 1, len(close)):
        average_gain = (average_gain * (window - 1) + float(gains.iloc[position])) / window
        average_loss = (average_loss * (window - 1) + float(losses.iloc[position])) / window
        result.iloc[position] = _rsi(average_gain, average_loss)
    return result


def _unknown_result(
    *,
    sma5: float | None,
    sma20: float | None,
    sma60: float | None,
    rsi14: float | None,
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
        rsi14=rsi14,
        rsi_state="UNKNOWN",
        rsi_bonus=0,
        rsi_reasons=(),
        status="UNKNOWN",
        reasons=("REQUIRED_DATA_UNKNOWN",),
        unknown_fields=tuple(unknown_fields),
        quality_components={},
        quality_reasons=(),
        quality_method=None,
        five_day_state="UNKNOWN",
    )


def _rsi_confirmation(
    validated: pd.DataFrame,
    rsi14_series: pd.Series,
    *,
    reaction: str,
) -> tuple[str, int, tuple[str, ...]]:
    current_rsi = float(rsi14_series.iloc[-1])
    previous_rsi = float(rsi14_series.iloc[-2])
    if current_rsi >= 70.0:
        return "OVERBOUGHT", 0, ("RSI_OVERBOUGHT",)
    if current_rsi < 50.0 and current_rsi < previous_rsi:
        return "WEAKENING_BELOW_50", 0, ("RSI_WEAKENING_BELOW_50",)
    if reaction in {"NONE", "SMA5_CLOSE_BREAK", "SMA20_CLOSE_BREAK"}:
        return "NEUTRAL", 0, ()

    reasons: list[str] = []
    bonus = 0
    if previous_rsi < 30.0 and current_rsi >= 30.0:
        bonus += 3
        reasons.append("RSI_OVERSOLD_RECOVERY")
        state = "OVERSOLD_RECOVERY"
    elif previous_rsi < 40.0 and current_rsi >= 40.0:
        bonus += 2
        reasons.append("RSI_40_RECOVERY")
        state = "RSI_40_RECOVERY"
    else:
        state = "NEUTRAL"

    price_lows = validated["low"]
    current_price_low = float(price_lows.iloc[-5:].min())
    previous_price_low = float(price_lows.iloc[-10:-5].min())
    current_rsi_low = float(rsi14_series.iloc[-5:].min())
    previous_rsi_low = float(rsi14_series.iloc[-10:-5].min())
    if current_price_low < previous_price_low and current_rsi_low > previous_rsi_low:
        bonus += 2
        reasons.append("RSI_BULLISH_DIVERGENCE")
        if state == "NEUTRAL":
            state = "BULLISH_DIVERGENCE"
    return state, bonus, tuple(reasons)


def _quality_bonus(
    validated: pd.DataFrame,
    *,
    reaction: str,
    sma5_series: pd.Series,
    sma20_series: pd.Series,
    sma60_series: pd.Series,
) -> tuple[int, dict[str, int], tuple[str, ...], str | None]:
    if reaction in {"NONE", "SMA5_CLOSE_BREAK", "SMA20_CLOSE_BREAK"}:
        return (
            0,
            {
                "strong_body": 0,
                "close_near_high": 0,
                "reaction_slope_up": 0,
                "golden_cross": 0,
            },
            (),
            None,
        )

    strong_body = _strong_body(validated)
    current_high = float(validated["high"].iloc[-1])
    current_low = float(validated["low"].iloc[-1])
    current_close = float(validated["close"].iloc[-1])
    candle_range = current_high - current_low
    close_position = (current_close - current_low) / candle_range if candle_range > 0 else None
    close_near_high = close_position is not None and close_position >= 0.70 - 1e-12

    reaction_series = {
        "SMA60_UPWARD_CROSS_STRONG_BULL": sma60_series,
        "SMA20_PULLBACK_RECOVERY": sma20_series,
        "SMA20_CLOSE_BREAK": sma20_series,
        "SMA5_RECOVERY": sma5_series,
        "SMA5_HOLD": sma5_series,
        "SMA5_CLOSE_BREAK": sma5_series,
    }.get(reaction)
    reaction_slope_up = (
        reaction_series is not None
        and pd.notna(reaction_series.iloc[-2])
        and pd.notna(reaction_series.iloc[-1])
        and reaction_series.iloc[-1] > reaction_series.iloc[-2]
    )
    previous_sma20 = sma20_series.iloc[-2]
    previous_sma60 = sma60_series.iloc[-2]
    current_sma20 = sma20_series.iloc[-1]
    current_sma60 = sma60_series.iloc[-1]
    golden_cross = (
        previous_sma20 <= previous_sma60 and current_sma20 > current_sma60
    )

    components = {
        "strong_body": 3 if strong_body else 0,
        "close_near_high": 2 if close_near_high else 0,
        "reaction_slope_up": 3 if reaction_slope_up else 0,
        "golden_cross": 2 if golden_cross else 0,
    }
    reason_names = (
        ("STRONG_BODY", strong_body),
        ("CLOSE_NEAR_HIGH", close_near_high),
        ("REACTION_SLOPE_UP", reaction_slope_up),
        ("GOLDEN_CROSS", golden_cross),
    )
    reasons = tuple(name for name, enabled in reason_names if enabled)
    return (
        sum(components.values()),
        components,
        reasons,
        "body_atr_ratio_and_recent_20_body_p80",
    )


def _strong_body(validated: pd.DataFrame) -> bool:
    bodies = (validated["close"] - validated["open"]).abs()
    atr14 = _atr_series(validated).iloc[-1]
    body_ratio = (
        float(bodies.iloc[-1] / atr14)
        if pd.notna(atr14) and atr14 > 0
        else 0.0
    )
    recent_bodies = bodies.tail(20)
    strong_body = (
        len(recent_bodies) == 20
        and body_ratio >= 0.8
        and bodies.iloc[-1] >= float(recent_bodies.quantile(0.8))
        and validated["close"].iloc[-1] > validated["open"].iloc[-1]
    )
    return strong_body


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
        if "close" in missing:
            missing.append("rsi14")
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            rsi14=None,
            unknown_fields=missing,
        )

    completed, index_unknown = _completed_bars(daily, as_of)
    if index_unknown:
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            rsi14=None,
            unknown_fields=list(index_unknown),
        )

    assert completed is not None
    validated, invalid_fields = _validated_ohlcv(completed)
    if invalid_fields:
        if "close" in invalid_fields:
            invalid_fields = (*invalid_fields, "rsi14")
        return _unknown_result(
            sma5=None,
            sma20=None,
            sma60=None,
            rsi14=None,
            unknown_fields=list(invalid_fields),
        )

    close = validated["close"]
    rsi14_series = _wilder_rsi_series(close)
    rsi14_value = rsi14_series.iloc[-1] if not rsi14_series.empty else float("nan")
    rsi14 = float(rsi14_value) if pd.notna(rsi14_value) and isfinite(float(rsi14_value)) else None
    sma5 = _sma(close, 5)
    sma20 = _sma(close, 20)
    sma60 = _sma(close, 60)
    unknown_fields = [
        name
        for name, value in (("SMA5", sma5), ("SMA20", sma20), ("SMA60", sma60))
        if value is None
    ]
    if rsi14 is None:
        unknown_fields.append("rsi14")
    if unknown_fields:
        return _unknown_result(
            sma5=sma5,
            sma20=sma20,
            sma60=sma60,
            rsi14=rsi14,
            unknown_fields=unknown_fields,
        )

    sma60_series = _sma_series(close, 60)
    sma20_series = _sma_series(close, 20)
    sma5_series = _sma_series(close, 5)
    previous_close = float(close.iloc[-2])
    current_close = float(close.iloc[-1])
    previous_sma60 = float(sma60_series.iloc[-2])
    current_sma60 = float(sma60_series.iloc[-1])
    current_sma20 = float(sma20)
    previous_sma5 = float(sma5_series.iloc[-2])
    current_sma5 = float(sma5_series.iloc[-1])
    current_open = float(validated["open"].iloc[-1])
    if current_close >= current_sma5:
        five_day_state = (
            "SMA5_RECOVERY" if previous_close < previous_sma5 else "SMA5_HOLD"
        )
    else:
        five_day_state = "SMA5_CLOSE_BREAK"
    strong_body = _strong_body(validated)
    if (
        previous_close <= previous_sma60
        and current_close > current_sma60
        and current_close > current_open
        and strong_body
    ):
        reaction = "SMA60_UPWARD_CROSS_STRONG_BULL"
        base_score = 10
    else:
        atr14 = _atr_series(validated).iloc[-1]
        current_low = float(validated["low"].iloc[-1])
        if (
            pd.notna(atr14)
            and atr14 > 0
            and current_close >= current_sma20
            and current_close > current_open
            and abs(current_low - current_sma20) <= 0.25 * float(atr14)
        ):
            reaction = "SMA20_PULLBACK_RECOVERY"
            base_score = 8
        else:
            previous_sma20 = float(sma20_series.iloc[-2])
            if previous_close >= previous_sma20 and current_close < current_sma20:
                reaction = "SMA20_CLOSE_BREAK"
                base_score = -8
            elif previous_close < previous_sma5 and current_close >= current_sma5:
                reaction = "SMA5_RECOVERY"
                base_score = 6
            elif current_close >= current_sma5:
                reaction = "SMA5_HOLD"
                base_score = 3
            elif previous_close >= previous_sma5 and current_close < current_sma5:
                reaction = "SMA5_CLOSE_BREAK"
                base_score = -4
            else:
                reaction = "NONE"
                base_score = 0

    quality_bonus, quality_components, quality_reasons, quality_method = _quality_bonus(
        validated,
        reaction=reaction,
        sma5_series=sma5_series,
        sma20_series=sma20_series,
        sma60_series=sma60_series,
    )
    rsi_state, rsi_bonus, rsi_reasons = _rsi_confirmation(
        validated,
        rsi14_series,
        reaction=reaction,
    )

    return DailyMAReaction(
        reaction=reaction,
        base_score=base_score,
        quality_bonus=quality_bonus,
        total_score=min(20, base_score + quality_bonus + rsi_bonus),
        sma5=sma5,
        sma20=sma20,
        sma60=sma60,
        rsi14=rsi14,
        rsi_state=rsi_state,
        rsi_bonus=rsi_bonus,
        rsi_reasons=rsi_reasons,
        status="KNOWN",
        reasons=(reaction,) if reaction != "NONE" else (),
        unknown_fields=(),
        quality_components=quality_components,
        quality_reasons=quality_reasons,
        quality_method=quality_method,
        five_day_state=five_day_state,
    )


score_daily_reaction = score_daily_ma_reaction


__all__ = [
    "DailyMAReactionInputs",
    "DailyMAReaction",
    "score_daily_ma_reaction",
    "score_daily_reaction",
]
