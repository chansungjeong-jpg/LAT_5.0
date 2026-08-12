from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Iterable

from lat5.leader_score import MarketLeader


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    name: str
    market: str
    sector: str
    leader_score: float
    trading_value_rank: int
    rise_rate_rank: int


@dataclass(frozen=True)
class WatchlistSnapshot:
    as_of: str
    entries: tuple[WatchlistEntry, ...]


def build_watchlist_snapshot(
    leaders: Iterable[MarketLeader],
    *,
    as_of: date | datetime,
    limit_per_market: int,
) -> WatchlistSnapshot:
    if limit_per_market <= 0:
        raise ValueError("limit_per_market must be positive")

    counts: dict[str, int] = {}
    entries: list[WatchlistEntry] = []
    for leader in leaders:
        count = counts.get(leader.market, 0)
        if count >= limit_per_market:
            continue
        counts[leader.market] = count + 1
        entries.append(
            WatchlistEntry(
                ticker=leader.ticker,
                name=leader.name,
                market=leader.market,
                sector=leader.sector,
                leader_score=leader.leader_score,
                trading_value_rank=leader.trading_value_rank,
                rise_rate_rank=leader.rise_rate_rank,
            )
        )
    return WatchlistSnapshot(as_of=as_of.isoformat(), entries=tuple(entries))


def compare_snapshots(
    before: set[str], after: set[str]
) -> dict[str, list[str]]:
    return {
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "retained": sorted(before & after),
    }


def write_watchlist_snapshot(path: str | Path, snapshot: WatchlistSnapshot) -> None:
    payload = {
        "as_of": snapshot.as_of,
        "entries": [
            {
                "ticker": entry.ticker,
                "name": entry.name,
                "market": entry.market,
                "sector": entry.sector,
                "leader_score": entry.leader_score,
                "trading_value_rank": entry.trading_value_rank,
                "rise_rate_rank": entry.rise_rate_rank,
            }
            for entry in snapshot.entries
        ],
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_watchlist_snapshot(path: str | Path) -> WatchlistSnapshot:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = tuple(WatchlistEntry(**entry) for entry in payload["entries"])
    return WatchlistSnapshot(as_of=payload["as_of"], entries=entries)
