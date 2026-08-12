from lat5.backtest import BacktestConfig
from lat5.cli import (
    build_parser,
    render_hourly_abc_support_report,
    render_hourly_breakout_report,
    render_hourly_pullback_reversal_report,
    render_report,
)


def test_cli_parser_accepts_backtest_paths_and_range():
    args = build_parser().parse_args(
        [
            "backtest",
            "--source-db",
            "source.db",
            "--watchlist",
            "watch.md",
            "--output-dir",
            "artifacts",
            "--start",
            "2026-03-03",
            "--end",
            "2026-08-07",
            "--ticker",
            "005930",
            "--strategy",
            "hourly-ma-or",
        ]
    )
    assert args.command == "backtest"
    assert args.start == "2026-03-03"
    assert args.output_dir == "artifacts"
    assert args.ticker == "005930"
    assert args.strategy == "hourly-ma-or"


def test_hourly_pullback_reversal_is_the_default_backtest_strategy():
    args = build_parser().parse_args(
        [
            "backtest", "--source-db", "source.db", "--watchlist", "watch.md",
            "--output-dir", "artifacts",
        ]
    )
    assert args.strategy == "hourly-pullback-reversal"


def test_location_filter_flag_defaults_off_and_can_be_enabled():
    off = build_parser().parse_args(
        ["backtest", "--source-db", "source.db", "--watchlist", "watch.md",
         "--output-dir", "artifacts"]
    )
    assert off.location_filter is False

    on = build_parser().parse_args(
        ["backtest", "--source-db", "source.db", "--watchlist", "watch.md",
         "--output-dir", "artifacts", "--location-filter"]
    )
    assert on.location_filter is True


def test_report_labels_result_as_technical_baseline():
    report = render_report(
        summary={
            "trades": 2,
            "win_rate": 0.5,
            "profit_factor": 1.2,
            "expectancy": 100.0,
            "net_pnl": 200.0,
            "return_pct": 0.2,
            "max_drawdown": 50.0,
        },
        diagnostics={
            "universe_symbols": 10,
            "daily_covered_symbols": 9,
            "minute_covered_symbols": 8,
            "anchor_count": 4,
            "abc_count": 2,
            "reason_counts": {"ABC_INVALID": 2},
            "missing_execution_strength": True,
            "full_strategy_validated": False,
        },
        config=BacktestConfig(),
        source_db="source.db",
        start="2026-03-03",
        end="2026-08-07",
    )
    assert "TECHNICAL BASELINE" in report
    assert "전체 전략 검증: 실패" in report
    assert "체결강도" in report


def test_hourly_breakout_report_labels_the_confirmed_rules():
    report = render_hourly_breakout_report(
        summary={
            "trades": 3,
            "win_rate": 2 / 3,
            "profit_factor": 1.5,
            "expectancy": 100.0,
            "net_pnl": 300.0,
            "return_pct": 0.3,
            "max_drawdown": 50.0,
        },
        diagnostics={
            "universe_symbols": 1,
            "minute_covered_symbols": 1,
            "hourly_covered_symbols": 1,
            "breakout_count": 4,
            "reason_counts": {"HOURLY_MA_OR_VOLUME": 3},
            "volume_multiple": 1.5,
            "target_r": 2.0,
        },
        config=BacktestConfig(),
        source_db="source.db",
        start="2026-03-03",
        end="2026-08-07",
        ticker="005930",
    )
    assert "MA60 또는 MA120" in report
    assert "거래량 1.5배" in report
    assert "목표 2.0R" in report


def test_hourly_abc_support_report_labels_the_confirmed_sequence():
    report = render_hourly_abc_support_report(
        summary={
            "trades": 1, "win_rate": 1.0, "profit_factor": float("inf"),
            "expectancy": 100.0, "net_pnl": 100.0, "return_pct": 0.1,
            "max_drawdown": 0.0,
        },
        diagnostics={
            "universe_symbols": 1, "minute_covered_symbols": 1,
            "hourly_covered_symbols": 1, "strong_breakout_count": 3,
            "abc_support_count": 2,
            "reason_counts": {"HOURLY_ABC_MA60_C_HIGH": 1}, "target_r": 2.0,
        },
        config=BacktestConfig(), source_db="source.db", start="2026-03-03",
        end="2026-08-07", ticker="005930",
    )
    assert "강한 60분봉 돌파" in report
    assert "60분봉 ABC" in report
    assert "C 고가를 5분봉 종가가 돌파" in report


def test_hourly_pullback_reversal_report_labels_entry_and_split_exit_rules():
    report = render_hourly_pullback_reversal_report(
        summary={
            "trades": 2, "win_rate": 0.5, "profit_factor": 1.1,
            "expectancy": 10.0, "net_pnl": 20.0, "return_pct": 0.02,
            "max_drawdown": 10.0,
        },
        diagnostics={
            "universe_symbols": 1, "minute_covered_symbols": 1,
            "hourly_covered_symbols": 1, "strong_breakout_count": 3,
            "pullback_count": 2, "reversal_trigger_count": 2,
            "reason_counts": {}, "partial_target_r": 1.0, "final_target_r": 2.0,
        },
        config=BacktestConfig(), source_db="source.db", start="2026-03-03",
        end="2026-08-07", ticker="005930",
    )

    assert "EMA60 ±1%" in report
    assert "직전 3개 5분봉 최고가" in report
    assert "1R에서 절반" in report
    assert "14:30" in report
