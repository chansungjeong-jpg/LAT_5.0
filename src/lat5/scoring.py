from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
from typing import Iterable


@dataclass(frozen=True)
class MetricScore:
    points: float
    max_points: float
    known: bool = True

    @classmethod
    def unknown(cls, max_points: float) -> "MetricScore":
        return cls(0.0, max_points, False)


@dataclass(frozen=True)
class SectorAssessment:
    status: str
    score_lower: float
    score_upper: float
    valid_members: int
    required_members: int


def _known_number(value: float | None) -> bool:
    return value is not None and isfinite(float(value))


def daily_trend(price: float | None, ema10: float | None, ema20: float | None) -> str:
    if not all(_known_number(value) for value in (price, ema10, ema20)):
        return "UNKNOWN"
    if price < ema20 or ema10 < ema20:
        return "REJECT"
    return "STRONG" if price >= ema10 else "PULLBACK"


def price_trend_points(
    price: float | None, ema10: float | None, ema20: float | None
) -> MetricScore:
    state = daily_trend(price, ema10, ema20)
    if state == "UNKNOWN":
        return MetricScore.unknown(30)
    return MetricScore({"STRONG": 30, "PULLBACK": 15, "REJECT": 0}[state], 30)


def _band_score(value: float | None, bands: tuple[tuple[float, float], ...], maximum: float) -> MetricScore:
    if not _known_number(value):
        return MetricScore.unknown(maximum)
    points = 0.0
    for lower_bound, band_points in bands:
        if float(value) >= lower_bound:
            points = band_points
    return MetricScore(points, maximum)


def turnover_points(ratio: float | None) -> MetricScore:
    return _band_score(
        ratio,
        ((0.8, 5), (1.0, 10), (1.2, 15), (1.5, 20), (2.0, 30)),
        30,
    )


def execution_strength_points(strength: float | None) -> MetricScore:
    return _band_score(
        strength,
        ((90, 5), (100, 10), (110, 15), (120, 20), (140, 25)),
        25,
    )


def foreign_flow_points(percent: float | None) -> MetricScore:
    return _band_score(
        percent,
        ((0.0, 0), (1e-12, 3), (0.5, 6), (1.0, 9), (2.0, 12), (3.0, 15)),
        15,
    )


def classify_sector(
    metrics: Iterable[MetricScore], valid_members: int, total_members: int
) -> SectorAssessment:
    required = max(3, ceil(total_members * 0.70))
    scores = tuple(metrics)
    lower = sum(score.points for score in scores if score.known)
    upper = lower + sum(score.max_points for score in scores if not score.known)

    if total_members <= 0 or valid_members < required:
        status = "DATA_UNKNOWN"
    elif all(score.known for score in scores):
        status = "BUY" if lower >= 70 else "WATCH" if lower >= 55 else "REJECT"
    elif lower >= 70:
        status = "BUY"
    elif upper < 55:
        status = "REJECT"
    else:
        status = "DATA_UNKNOWN"

    return SectorAssessment(status, lower, upper, valid_members, required)
