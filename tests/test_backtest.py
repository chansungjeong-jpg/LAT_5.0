import sqlite3

import pandas as pd

from lat5.backtest import (
    BacktestConfig,
    infer_tick_size,
    run_technical_baseline,
    simulate_fixed_trade,
    summarize_trades,
)
from lat5.data import (
    KiwoomDataStore,
    WatchItem,
    aggregate_60m,
    aggregate_weekly,
    daily_ema_context,
    parse_watchlist,
)
from lat5.patterns import ABCSetup
from lat5.collector_store import CollectorStore
from datetime import datetime


def test_parse_watchlist_reads_core_only_and_excludes_forbidden_sectors(tmp_path):
    path = tmp_path / "watchlist.md"
    path.write_text(
        """# Watchlist
## 3. Core Watchlist
### 3.1 Semiconductor
| rank | name | code | role |
|---:|---|---:|---|
| 1 | Alpha | 005930 | leader |
### 3.2 Game Content
| rank | name | code | role |
|---:|---|---:|---|
| 1 | Excluded | 123456 | game |
## 4. Ranking
### Dynamic
| 1 | Outside | 999999 | no |
""",
        encoding="utf-8",
    )
    items = parse_watchlist(path)
    assert [(item.ticker, item.name, item.sector) for item in items] == [
        ("005930", "Alpha", "Semiconductor")
    ]


def test_aggregate_60m_uses_session_aligned_blocks():
    index = pd.date_range("2026-08-07 09:00", periods=15, freq="5min")
    bars = pd.DataFrame(
        {
            "open": range(100, 115),
            "high": range(101, 116),
            "low": range(99, 114),
            "close": range(100, 115),
            "volume": [10] * 15,
            "amount": [1_000] * 15,
        },
        index=index,
    )
    hourly = aggregate_60m(bars)
    assert len(hourly) == 2
    assert hourly.iloc[0].to_dict() == {
        "open": 100,
        "high": 112,
        "low": 99,
        "close": 111,
        "volume": 120,
        "amount": 12_000,
    }
    assert hourly.index[0] == pd.Timestamp("2026-08-07 09:00")


def test_aggregate_weekly_uses_completed_daily_bars():
    dates = pd.date_range("2026-08-03", periods=10, freq="D")
    daily = pd.DataFrame(
        {
            "open": range(100, 110),
            "high": range(101, 111),
            "low": range(99, 109),
            "close": range(100, 110),
            "volume": [10] * 10,
            "amount": [100] * 10,
        },
        index=dates,
    )

    weekly = aggregate_weekly(daily)

    assert weekly.index[0] == pd.Timestamp("2026-08-07")
    assert weekly.loc[pd.Timestamp("2026-08-07"), "close"] == 104


def test_daily_ema_context_uses_only_prior_completed_days():
    dates = pd.date_range("2026-01-01", periods=25, freq="D")
    daily = pd.DataFrame({"close": range(100, 125)}, index=dates)
    context = daily_ema_context(daily)
    expected = daily["close"].iloc[:-1].ewm(span=10, adjust=False, min_periods=10).mean().iloc[-1]
    assert context.loc[dates[-1], "ema10"] == expected
    changed = daily.copy()
    changed.loc[dates[-1], "close"] = 10_000
    assert daily_ema_context(changed).loc[dates[-1], "ema10"] == expected


def test_data_store_reads_existing_schema_without_writes(tmp_path):
    db_path = tmp_path / "source.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ohlcv (ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, amount REAL)"
    )
    conn.execute(
        "CREATE TABLE ohlcv_minute (ticker TEXT, datetime TEXT, interval TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER)"
    )
    conn.execute("INSERT INTO ohlcv VALUES ('005930','20260807',1,2,0.5,1.5,100,150)")
    conn.execute("INSERT INTO ohlcv_minute VALUES ('005930','20260807090000','5',1,2,0.5,1.5,100)")
    conn.commit()
    conn.close()

    with KiwoomDataStore(db_path) as store:
        assert len(store.load_daily("005930")) == 1
        assert len(store.load_minutes("005930")) == 1
        try:
            store.conn.execute("DELETE FROM ohlcv")
        except sqlite3.OperationalError as exc:
            assert "readonly" in str(exc).lower()
        else:
            raise AssertionError("source DB accepted a write")


def test_data_store_reads_lat_provider_schema(tmp_path):
    db_path = tmp_path / "lat.db"
    with CollectorStore(db_path) as collector:
        run_id = collector.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        collector.save_daily(run_id, [{
            "ticker": "005930", "date": "2026-08-07", "open": 1, "high": 2,
            "low": 0.5, "close": 1.5, "volume": 100, "amount": 150,
        }])
        collector.save_minutes(run_id, [{
            "ticker": "005930", "datetime": "2026-08-07T09:00:00", "interval": "5",
            "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100,
            "amount": 150,
        }])
        collector.save_foreign_flow(run_id, [{
            "ticker": "005930", "date": "2026-08-07", "foreign_net_thousand": -25,
        }])

    with KiwoomDataStore(db_path) as store:
        assert store.load_daily("005930").iloc[0]["amount"] == 150
        assert store.load_minutes("005930").iloc[0]["amount"] == 150
        assert store.load_foreign_flow("005930").iloc[0]["foreign_net"] == -25


def test_summarize_trades_reports_pf_expectancy_and_drawdown():
    trades = pd.DataFrame({"net_pnl": [100.0, -50.0, 150.0, -25.0]})
    summary = summarize_trades(trades, initial_capital=1_000.0)
    assert summary["trades"] == 4
    assert summary["win_rate"] == 0.5
    assert round(summary["profit_factor"], 3) == 3.333
    assert summary["expectancy"] == 43.75
    assert summary["max_drawdown"] == 50.0


def test_tick_size_is_inferred_from_observed_kiwoom_prices():
    bars = pd.DataFrame(
        {
            "open": [1000, 1005],
            "high": [1010, 1015],
            "low": [995, 1000],
            "close": [1005, 1010],
        }
    )
    assert infer_tick_size(bars) == 5
    assert infer_tick_size(pd.DataFrame({"open": [100], "high": [100], "low": [100], "close": [100]})) is None


def test_simulate_fixed_trade_recalculates_rr_and_costs():
    bars = pd.DataFrame(
        {
            "open": [99, 101, 103],
            "high": [103, 106, 111],
            "low": [98, 100, 102],
            "close": [101, 104, 110],
        },
        index=pd.date_range("2026-08-07 10:00", periods=3, freq="5min"),
    )
    setup = ABCSetup(0, 0, 0, 0, -2, entry=100, stop=95, expires_pos=0)
    config = BacktestConfig(
        commission_bps=0,
        sell_tax_bps=0,
        slippage_bps=0,
        min_rr=1.5,
    )
    trade = simulate_fixed_trade(
        bars,
        setup,
        tick_size=1,
        channel_upper=110,
        equity=100_000,
        config=config,
        entry_start_pos=0,
        entry_end_pos=1,
    )
    assert trade is not None
    assert trade["entry_price"] == 100
    assert trade["exit_price"] == 110
    assert trade["exit_reason"] == "TARGET"
    assert trade["net_pnl"] == 1000


def test_simulate_fixed_trade_rejects_fill_when_actual_rr_is_too_low():
    bars = pd.DataFrame(
        {"open": [102], "high": [103], "low": [101], "close": [102]},
        index=[pd.Timestamp("2026-08-07 10:00")],
    )
    setup = ABCSetup(0, 0, 0, 0, 0, entry=100, stop=95, expires_pos=0)
    assert simulate_fixed_trade(
        bars,
        setup,
        tick_size=1,
        channel_upper=110,
        equity=100_000,
        config=BacktestConfig(slippage_bps=0),
        entry_start_pos=0,
        entry_end_pos=0,
    ) is None


def test_baseline_reports_missing_minute_coverage_without_crashing(tmp_path):
    class EmptyMinuteStore:
        def load_daily(self, ticker):
            index = pd.date_range("2026-01-01", periods=25, freq="D")
            return pd.DataFrame({"close": range(100, 125)}, index=index)

        def load_minutes(self, ticker):
            return pd.DataFrame()

    trades, summary, diagnostics = run_technical_baseline(
        EmptyMinuteStore(),
        [WatchItem("005930", "Alpha", "Semiconductor")],
        output_db=tmp_path / "paper.db",
        config=BacktestConfig(),
    )
    assert trades.empty
    assert summary["trades"] == 0
    assert diagnostics["universe_symbols"] == 1
    assert diagnostics["minute_covered_symbols"] == 0
    assert diagnostics["missing_execution_strength"] is True
