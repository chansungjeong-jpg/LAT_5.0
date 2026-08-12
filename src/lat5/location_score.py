from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class LocationInputs:
    market_state: str | None
    sector_score: float | None
    leader_ok: bool | None
    weekly_trend_ok: bool | None
    daily_trend_ok: bool | None
    recent_5d_bullish_count: int | None
    price: float | None
    ema60: float | None
    ema120: float | None
    m60_slope_pct: float | None
    volume_ratio: float | None
    m5_distance_pct: float | None
    daily_distance_pct: float | None
    supply_distance_pct: float | None
    rr: float | None
    golden_cross_ok: bool | None = False


@dataclass(frozen=True)
class LocationDecision:
    state: str
    score: int
    components: dict[str, int]
    vetoes: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    reasons: tuple[str, ...]


def _known(value: object) -> bool:
    return value is not None and isfinite(float(value))


def _volume_score(ratio: float) -> int:
    if ratio < 0.8:
        return 0
    if ratio < 1.0:
        return 5
    if ratio < 1.2:
        return 10
    if ratio < 1.5:
        return 15
    if ratio < 2.0:
        return 20
    return 30


def _m60_location_score(price: float, ema60: float, ema120: float) -> int:
    if price >= ema60 >= ema120:
        return 25
    if price >= ema60:
        return 15
    if price >= ema120:
        return 10
    return 0


def _slope_score(slope_pct: float) -> int:
    if slope_pct <= 0:
        return 0
    if slope_pct < 0.005:
        return 5
    return 10


def score_location(inputs: LocationInputs) -> LocationDecision:
    unknown: list[str] = []
    vetoes: list[str] = []
    reasons: list[str] = []

    required = (
        "market_state", "sector_score", "leader_ok", "weekly_trend_ok",
        "daily_trend_ok", "recent_5d_bullish_count", "price", "ema60",
        "ema120", "m60_slope_pct", "volume_ratio", "m5_distance_pct",
        "daily_distance_pct", "supply_distance_pct", "rr",
    )
    non_numeric = {
        "market_state", "leader_ok", "weekly_trend_ok", "daily_trend_ok",
        "recent_5d_bullish_count",
    }
    for name in required:
        value = getattr(inputs, name)
        if (value is None) if name in non_numeric else not _known(value):
            unknown.append(name)

    if unknown:
        return LocationDecision("REJECT", 0, {}, (), tuple(unknown), ("REQUIRED_DATA_UNKNOWN",))

    if inputs.market_state not in {"BUY", "SELECTIVE_BUY"}:
        vetoes.append("MARKET_NOT_BUYABLE")
    if float(inputs.sector_score) < 60:
        vetoes.append("SECTOR_SCORE_BELOW_60")
    if not inputs.leader_ok:
        vetoes.append("NOT_LEADER_CANDIDATE")
    if not inputs.weekly_trend_ok:
        vetoes.append("WEEKLY_TREND_INVALID")
    if not inputs.daily_trend_ok:
        vetoes.append("DAILY_TREND_INVALID")
    if float(inputs.supply_distance_pct) <= 0:
        vetoes.append("SUPPLY_PROXY_INVALID")
    if float(inputs.rr) < 1.5:
        vetoes.append("RR_BELOW_1_5")

    components = {
        "volume": _volume_score(float(inputs.volume_ratio)),
        "m60_location": _m60_location_score(
            float(inputs.price), float(inputs.ema60), float(inputs.ema120)
        ),
        "weekly_trend": 15 if inputs.weekly_trend_ok else 0,
        "daily_trend": 15 if inputs.daily_trend_ok else 0,
        "slope": _slope_score(float(inputs.m60_slope_pct)),
        "recent_5d_bullish": (
            5 if int(inputs.recent_5d_bullish_count) >= 4
            else 3 if int(inputs.recent_5d_bullish_count) >= 2 else 0
        ),
        "golden_cross": 3 if inputs.golden_cross_ok else 0,
    }
    score = sum(components.values())

    if float(inputs.m5_distance_pct) > 0.03:
        vetoes.append("M5_DISTANCE_OVERHEATED")
    if float(inputs.daily_distance_pct) > 0.10:
        vetoes.append("DAILY_DISTANCE_OVERHEATED")

    hard_vetoes = {
        "MARKET_NOT_BUYABLE", "SECTOR_SCORE_BELOW_60", "NOT_LEADER_CANDIDATE",
        "WEEKLY_TREND_INVALID", "DAILY_TREND_INVALID", "SUPPLY_PROXY_INVALID",
        "RR_BELOW_1_5",
    }
    if any(v in hard_vetoes for v in vetoes):
        state = "REJECT"
    elif any(v in vetoes for v in ("M5_DISTANCE_OVERHEATED", "DAILY_DISTANCE_OVERHEATED")):
        state = "WATCH"
    elif score >= 70:
        state = "BUY"
    elif score >= 50:
        state = "WATCH"
    else:
        state = "REJECT"

    return LocationDecision(state, score, components, tuple(vetoes), (), tuple(reasons))
