import pytest

from lat5.candidate_board import build_candidate_board


def _filter_rows():
    return [
        {"ticker": "000111", "name": "가나전자", "sector": "반도체", "provisional": True},
        {"ticker": "000222", "name": "나다화학", "sector": "화학", "provisional": False},
        {"ticker": "000333", "name": "다라로봇", "sector": "로봇", "provisional": True},
    ]


def _rs_rows():
    return [
        {"ticker": "000333", "name": "다라로봇", "rs": 0.42, "stock_return": 0.55},
        {"ticker": "000111", "name": "가나전자", "rs": 0.18, "stock_return": 0.31},
        {"ticker": "000999", "name": "무관종목", "rs": 0.90, "stock_return": 1.10},
    ]


def test_board_only_includes_stage1_filter_survivors():
    """final_spec ch.0 is an immutable contract: nothing that failed the
    monthly10/weekly5 recovery filter may be ranked or scored downstream,
    no matter how strong its relative strength is."""
    board = build_candidate_board(filter_rows=_filter_rows(), rs_rows=_rs_rows())

    assert [row.ticker for row in board] == ["000333", "000111", "000222"]
    assert "000999" not in [row.ticker for row in board]


def test_board_ranks_by_relative_strength_descending():
    board = build_candidate_board(filter_rows=_filter_rows(), rs_rows=_rs_rows())

    assert board[0].ticker == "000333"
    assert board[0].rs == pytest.approx(0.42)
    assert board[1].ticker == "000111"
    assert board[1].rs == pytest.approx(0.18)


def test_filter_survivor_without_rs_data_sorts_last_as_unknown():
    board = build_candidate_board(filter_rows=_filter_rows(), rs_rows=_rs_rows())

    last = board[-1]
    assert last.ticker == "000222"
    assert last.rs is None


def test_board_attaches_position_score_and_breakout_evidence_when_present():
    decisions = [
        {
            "symbol": "000111",
            "location_score": 64,
            "final_state": "WATCH_HIGH",
            "entry_eligible": False,
            "vetoes": ["NO_PULLBACK"],
            "breakout_entry_price": 12345.0,
            "breakout_rr": 2.4,
        }
    ]
    board = build_candidate_board(
        filter_rows=_filter_rows(), rs_rows=_rs_rows(), location_decisions=decisions
    )

    row = next(row for row in board if row.ticker == "000111")
    assert row.location_score == 64
    assert row.final_state == "WATCH_HIGH"
    assert row.entry_eligible is False
    assert row.vetoes == ["NO_PULLBACK"]
    assert row.breakout_entry_price == pytest.approx(12345.0)
    assert row.breakout_rr == pytest.approx(2.4)


def test_board_leaves_position_fields_unknown_when_no_decision_exists():
    board = build_candidate_board(filter_rows=_filter_rows(), rs_rows=_rs_rows())

    row = board[0]
    assert row.location_score is None
    assert row.final_state is None
    assert row.entry_eligible is None
    assert row.vetoes == []


def test_board_keeps_the_latest_decision_when_a_symbol_has_several():
    decisions = [
        {"symbol": "000111", "location_score": 40, "evaluated_at": "2026-08-01 10:00:00"},
        {"symbol": "000111", "location_score": 71, "evaluated_at": "2026-09-01 10:00:00"},
    ]
    board = build_candidate_board(
        filter_rows=_filter_rows(), rs_rows=_rs_rows(), location_decisions=decisions
    )

    row = next(row for row in board if row.ticker == "000111")
    assert row.location_score == 71


def test_empty_filter_result_produces_empty_board():
    assert build_candidate_board(filter_rows=[], rs_rows=_rs_rows()) == []
