from datetime import date

from lat5.leader_score import MarketLeaderInput, rank_market_leaders
from lat5.leader_watchlist import (
    build_watchlist_snapshot,
    compare_snapshots,
    read_watchlist_snapshot,
    write_watchlist_snapshot,
)


def test_build_watchlist_snapshot_limits_each_market_independently():
    leaders = rank_market_leaders(
        [
            MarketLeaderInput("K1", "K1", "KOSPI", "semi", 1000, 10),
            MarketLeaderInput("K2", "K2", "KOSPI", "semi", 900, 9),
            MarketLeaderInput("Q1", "Q1", "KOSDAQ", "bio", 1000, 20),
        ]
    )

    snapshot = build_watchlist_snapshot(leaders, as_of=date(2026, 8, 12), limit_per_market=1)

    assert [entry.ticker for entry in snapshot.entries] == ["Q1", "K1"]
    assert snapshot.as_of == "2026-08-12"


def test_compare_snapshots_reports_added_removed_and_retained_symbols():
    before = {"K1", "K2"}
    after = {"K1", "Q1"}

    diff = compare_snapshots(before, after)

    assert diff == {"added": ["Q1"], "removed": ["K2"], "retained": ["K1"]}


def test_watchlist_snapshot_round_trips_as_json(tmp_path):
    leaders = rank_market_leaders([
        MarketLeaderInput("K1", "K1", "KOSPI", "semi", 1000, 10),
    ])
    snapshot = build_watchlist_snapshot(
        leaders, as_of=date(2026, 8, 12), limit_per_market=1
    )
    path = tmp_path / "watchlist_snapshot.json"

    write_watchlist_snapshot(path, snapshot)

    assert read_watchlist_snapshot(path) == snapshot
