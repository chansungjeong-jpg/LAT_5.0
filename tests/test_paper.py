import sqlite3

from lat5.paper import PaperLedger, paper_entry_fill, paper_exit_fill, size_position


def test_size_position_respects_risk_and_exposure_caps():
    assert size_position(100_000_000, entry=10_000, stop=9_500) == 1_000
    assert size_position(100_000_000, entry=100_000, stop=99_900) == 200
    assert size_position(100_000_000, entry=10_000, stop=10_000) == 0


def test_entry_fill_does_not_chase_above_limit():
    assert paper_entry_fill(100, 102, next_open=103, bar_high=105, slippage_bps=0) is None
    assert paper_entry_fill(100, 102, next_open=99, bar_high=99.5, slippage_bps=0) is None
    assert paper_entry_fill(100, 102, next_open=101, bar_high=103, slippage_bps=0) == 101


def test_exit_fill_is_stop_first_and_uses_gap_price():
    both = paper_exit_fill(stop=95, target=110, bar_open=100, bar_high=112, bar_low=94, slippage_bps=0)
    assert both == (95, "STOP")
    gap = paper_exit_fill(stop=95, target=110, bar_open=92, bar_high=96, bar_low=90, slippage_bps=0)
    assert gap == (92, "STOP_GAP")


def test_ledger_persists_decision_order_fill_and_version(tmp_path):
    db_path = tmp_path / "paper.db"
    with PaperLedger(db_path) as ledger:
        decision_id = ledger.record_decision(
            timestamp="2026-08-07T10:00:00",
            ticker="005930",
            sector="semiconductor",
            decision="BUY",
            reason="ABC_BREAKOUT",
            strategy_id="lat5-fixed",
            algorithm_version="0.1.0",
            inputs={"entry": 100.0, "stop": 95.0},
        )
        order_id = ledger.create_order(
            decision_id=decision_id,
            trigger_price=100,
            limit_price=102,
            stop_price=95,
            target_price=110,
            quantity=10,
            created_at="2026-08-07T10:00:00",
            expires_at="2026-08-07T10:15:00",
        )
        ledger.record_fill(order_id, "2026-08-07T10:05:00", 101, 10, "ENTRY", 50, 0, 1)

    conn = sqlite3.connect(db_path)
    decision = conn.execute(
        "SELECT strategy_id, algorithm_version, decision FROM decisions"
    ).fetchone()
    order = conn.execute("SELECT status, quantity FROM orders").fetchone()
    fill = conn.execute("SELECT price, fill_type, fee FROM fills").fetchone()
    assert decision == ("lat5-fixed", "0.1.0", "BUY")
    assert order == ("FILLED", 10)
    assert fill == (101.0, "ENTRY", 50.0)


def test_ledger_keeps_strategy_versions_separate(tmp_path):
    with PaperLedger(tmp_path / "paper.db") as ledger:
        for version in ("0.1.0", "0.2.0"):
            ledger.record_decision(
                "2026-08-07T10:00:00",
                "005930",
                "semiconductor",
                "WATCH",
                "RR_LOW",
                "lat5-fixed",
                version,
                {},
            )
        assert ledger.decision_count("lat5-fixed", "0.1.0") == 1
        assert ledger.decision_count("lat5-fixed", "0.2.0") == 1
