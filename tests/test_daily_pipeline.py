from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_daily_signal_reports import build_pipeline_commands


def test_daily_pipeline_runs_collection_health_before_selection(tmp_path):
    commands = build_pipeline_commands(
        python="python",
        root=tmp_path,
        as_of="2026-08-15",
    )
    assert commands[0][2:4] == ["lat5.cli", "collect"]
    assert commands[1][2:4] == ["lat5.cli", "data-health"]
    assert commands[2][1].endswith("filter_monthly10_weekly5.py")
    assert commands[3][1].endswith("scan_trendline_rank.py")


def test_daily_pipeline_uses_same_database_and_watchlist(tmp_path):
    commands = build_pipeline_commands(python="python", root=tmp_path, as_of="2026-08-15")
    for command in commands[:2]:
        assert str(tmp_path / "data" / "lat5_market.db") in command
        assert str(tmp_path / "LAT_SIMPLE_v1.0_Watchlist.md") in command
