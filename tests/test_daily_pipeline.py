import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_daily_signal_reports import _subprocess_env, build_pipeline_commands


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
    assert commands[4][2:4] == ["lat5.cli", "backtest"]
    assert commands[5][1].endswith("relative_strength_scan.py")
    assert commands[6][1].endswith("build_dashboard.py")


def test_daily_pipeline_dashboard_backtest_uses_lookback_window_and_overwrites(tmp_path):
    commands = build_pipeline_commands(python="python", root=tmp_path, as_of="2026-08-15")
    backtest = commands[4]
    assert "--start" in backtest
    assert backtest[backtest.index("--start") + 1] == "2026-06-16"
    assert "--end" in backtest
    assert backtest[backtest.index("--end") + 1] == "2026-08-15"
    assert "--overwrite" in backtest
    assert "--location-filter" in backtest
    assert str(tmp_path / "artifacts" / "latest_scoring") in backtest


def test_daily_pipeline_runs_relative_strength_scan_before_dashboard(tmp_path):
    commands = build_pipeline_commands(python="python", root=tmp_path, as_of="2026-08-15")
    rs_command = commands[5]
    assert rs_command[1].endswith("relative_strength_scan.py")
    assert "--as-of" in rs_command
    assert rs_command[rs_command.index("--as-of") + 1] == "2026-08-15"
    assert str(tmp_path / "data" / "lat5_market.db") in rs_command
    assert str(tmp_path / "LAT_SIMPLE_v1.0_Watchlist.md") in rs_command


def test_daily_pipeline_uses_same_database_and_watchlist(tmp_path):
    commands = build_pipeline_commands(python="python", root=tmp_path, as_of="2026-08-15")
    for command in commands[:2]:
        assert str(tmp_path / "data" / "lat5_market.db") in command
        assert str(tmp_path / "LAT_SIMPLE_v1.0_Watchlist.md") in command


def test_subprocess_env_adds_src_to_pythonpath_even_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = _subprocess_env(tmp_path)
    assert env["PYTHONPATH"] == str(tmp_path / "src")


def test_subprocess_env_prepends_src_ahead_of_existing_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", "/some/other/path")
    env = _subprocess_env(tmp_path)
    assert env["PYTHONPATH"].split(os.pathsep) == [
        str(tmp_path / "src"),
        "/some/other/path",
    ]
