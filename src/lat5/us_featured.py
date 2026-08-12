from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from lat5.us_mapping import mappings_for


@dataclass(frozen=True)
class USFeaturedInput:
    symbol: str
    change_pct: float
    volume_ratio: float
    trading_value: float


@dataclass(frozen=True)
class USFeaturedStock:
    symbol: str
    flow: str
    change_pct: float
    volume_ratio: float
    trading_value: float
    featured_score: float
    reason: str


def _rank_desc(rows: list[USFeaturedInput], field: str) -> dict[str, int]:
    ordered = sorted(rows, key=lambda row: (-getattr(row, field), row.symbol))
    return {row.symbol: index for index, row in enumerate(ordered, start=1)}


def select_us_featured_stocks(
    rows: Iterable[USFeaturedInput], *, top_n: int
) -> tuple[USFeaturedStock, ...]:
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    candidates = []
    for row in rows:
        mapping = mappings_for(row.symbol)
        if mapping is None or row.change_pct <= 0:
            continue
        if not all(isfinite(float(value)) for value in (
            row.change_pct, row.volume_ratio, row.trading_value
        )):
            continue
        if row.volume_ratio <= 0 or row.trading_value <= 0:
            continue
        candidates.append(row)

    if not candidates:
        return ()

    rise_rank = _rank_desc(candidates, "change_pct")
    volume_rank = _rank_desc(candidates, "volume_ratio")
    value_rank = _rank_desc(candidates, "trading_value")
    count = len(candidates)

    def percentile(rank: int) -> float:
        return 100.0 if count == 1 else 100.0 * (count - rank) / (count - 1)

    selected = []
    for row in candidates:
        score = (
            percentile(rise_rank[row.symbol])
            + percentile(volume_rank[row.symbol])
            + percentile(value_rank[row.symbol])
        ) / 3.0
        selected.append(
            USFeaturedStock(
                row.symbol,
                mappings_for(row.symbol).flow,
                row.change_pct,
                row.volume_ratio,
                row.trading_value,
                score,
                "RISE_VOLUME_TRADING_VALUE_RANKED",
            )
        )

    return tuple(sorted(
        selected,
        key=lambda item: (-item.featured_score, item.symbol),
    )[:top_n])
