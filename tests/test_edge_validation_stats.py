import pandas as pd
import pytest

from lat5.edge_validation import (
    EntryResult,
    FlowResult,
    LocationResult,
    OutcomeResult,
    RecoveryResult,
    TickerDayRecord,
)
from lat5.edge_validation_stats import (
    build_comparisons,
    independent_block_count,
    location_bin,
    rank_top_n,
    split_tertiles,
    summarize_group,
    veto_cooccurrence,
)

_NO_RECOVERY = RecoveryResult(False, None, None, None, "NOT_RECOVERED")
_NO_LOCATION = LocationResult(None, None, (), None, False, (), None)
_NO_ENTRY = EntryResult("UNFILLED", None, None, None, "NO_NEXT_SESSION_IN_CALENDAR")
_NO_FLOW = FlowResult(None, 5, None, "FLOW_DATA_MISSING")
_PASS_RECOVERY = RecoveryResult(True, False, None, None, None)


def _mature(gross: float, net: float | None = None) -> OutcomeResult:
    return OutcomeResult(
        "MATURE", pd.Timestamp("2026-08-20"), 100.0, gross,
        net if net is not None else gross, gross, -abs(gross), 10, 10,
    )


def _record(day: str, ticker: str, hold_days: int, outcome: OutcomeResult | None) -> TickerDayRecord:
    outcomes = {} if outcome is None else {hold_days: outcome}
    return TickerDayRecord(
        eval_day=pd.Timestamp(day), ticker=ticker, name=ticker, sectors=(),
        recovery=_NO_RECOVERY, rs=None, stock_return=None, location=_NO_LOCATION,
        entry=_NO_ENTRY, outcomes=outcomes,
        entry_close=_NO_ENTRY, outcomes_close_to_open={},
        flow=_NO_FLOW,
    )


# ---------------------------------------------------------------------------
# rank_top_n / split_tertiles
# ---------------------------------------------------------------------------


def test_rank_top_n_orders_by_value_descending():
    candidates = [("000660", 0.05), ("005930", 0.10), ("035420", 0.02)]

    assert rank_top_n(candidates, 2) == {"005930", "000660"}


def test_rank_top_n_ties_broken_by_ticker_code_ascending():
    candidates = [("999999", 0.05), ("000001", 0.05), ("500000", 0.05)]

    assert rank_top_n(candidates, 1) == {"000001"}


def test_split_tertiles_distributes_remainder_to_earlier_groups():
    candidates = [(str(i), float(10 - i)) for i in range(7)]  # 7 items, sizes 3/2/2

    top, mid, bottom = split_tertiles(candidates)

    assert len(top) == 3 and len(mid) == 2 and len(bottom) == 2
    assert top == {"0", "1", "2"}
    assert bottom == {"5", "6"}


def test_split_tertiles_empty_input():
    assert split_tertiles([]) == (set(), set(), set())


# ---------------------------------------------------------------------------
# location_bin
# ---------------------------------------------------------------------------


def test_location_bin_boundaries():
    assert location_bin(0) == "0-39"
    assert location_bin(39) == "0-39"
    assert location_bin(40) == "40-59"
    assert location_bin(59) == "40-59"
    assert location_bin(60) == "60-79"
    assert location_bin(79) == "60-79"
    assert location_bin(80) == "80-100"
    assert location_bin(100) == "80-100"


# ---------------------------------------------------------------------------
# independent_block_count
# ---------------------------------------------------------------------------


def test_independent_block_count_overlapping_holds_collapse_to_one_block():
    calendar = list(pd.bdate_range("2026-08-10", periods=20))
    eval_days = calendar[0:7]  # 7 consecutive days, hold_days=10 overlaps them all

    assert independent_block_count(eval_days, hold_days=10, calendar=calendar) == 1


def test_independent_block_count_widely_spaced_days_are_independent():
    calendar = list(pd.bdate_range("2026-08-10", periods=40))
    eval_days = [calendar[0], calendar[15], calendar[30]]

    assert independent_block_count(eval_days, hold_days=10, calendar=calendar) == 3


# ---------------------------------------------------------------------------
# summarize_group
# ---------------------------------------------------------------------------


def test_summarize_group_pools_across_days_and_averages_by_day():
    records = [
        _record("2026-08-13", "A", 10, _mature(0.10)),
        _record("2026-08-13", "B", 10, _mature(0.20)),  # day mean = 0.15
        _record("2026-08-14", "C", 10, _mature(0.30)),  # day mean = 0.30
        _record("2026-08-14", "D", 10, None),  # unfilled -- excluded
    ]

    stats = summarize_group(records, hold_days=10)

    assert stats.n_observations == 3
    assert stats.n_eval_days == 2
    assert stats.mean_gross_pooled == pytest.approx((0.10 + 0.20 + 0.30) / 3)
    assert stats.mean_gross_daily_avg == pytest.approx((0.15 + 0.30) / 2)


def test_summarize_group_empty_when_nothing_matured():
    records = [_record("2026-08-13", "A", 10, None)]

    stats = summarize_group(records, hold_days=10)

    assert stats.n_observations == 0
    assert stats.mean_gross_pooled is None


def test_summarize_group_ignores_other_hold_periods():
    records = [_record("2026-08-13", "A", 5, _mature(0.10))]

    stats = summarize_group(records, hold_days=10)

    assert stats.n_observations == 0


# ---------------------------------------------------------------------------
# veto_cooccurrence
# ---------------------------------------------------------------------------


def test_veto_cooccurrence_counts_each_veto_across_records():
    counts = veto_cooccurrence([("RR_TOO_LOW", "NO_PULLBACK"), ("RR_TOO_LOW",), ()])

    assert counts == {"RR_TOO_LOW": 2, "NO_PULLBACK": 1}


# ---------------------------------------------------------------------------
# H-002: build_comparisons buckets foreign-flow / execution-strength tertiles
# ---------------------------------------------------------------------------


def _flow_record(day: str, ticker: str, *, foreign_net: float, strength: float, gross: float) -> TickerDayRecord:
    return TickerDayRecord(
        eval_day=pd.Timestamp(day), ticker=ticker, name=ticker, sectors=(),
        recovery=_PASS_RECOVERY, rs=None, stock_return=None, location=_NO_LOCATION,
        entry=_NO_ENTRY, outcomes={10: _mature(gross)},
        entry_close=_NO_ENTRY, outcomes_close_to_open={},
        flow=FlowResult(foreign_net, 5, strength, None),
    )


def test_build_comparisons_ranks_foreign_and_strength_tertiles_per_day():
    day = "2026-08-13"
    # foreign_net descending == return descending, so top/bottom groups are
    # unambiguous: top tertile should be the two highest-foreign-net tickers.
    records = [
        _flow_record(day, "A", foreign_net=60.0, strength=10.0, gross=0.06),
        _flow_record(day, "B", foreign_net=50.0, strength=20.0, gross=0.05),
        _flow_record(day, "C", foreign_net=40.0, strength=30.0, gross=0.04),
        _flow_record(day, "D", foreign_net=30.0, strength=40.0, gross=0.03),
        _flow_record(day, "E", foreign_net=20.0, strength=50.0, gross=0.02),
        _flow_record(day, "F", foreign_net=10.0, strength=60.0, gross=0.01),
    ]
    eval_days = [pd.Timestamp(day)]
    calendar = [pd.Timestamp(day)]

    comparisons = build_comparisons(records, eval_days, calendar, holds=(10,), rs_days=20)

    stage = comparisons["hold_10"]
    assert stage["foreign_top"].n_observations == 2
    assert stage["foreign_top"].mean_gross_pooled == pytest.approx((0.06 + 0.05) / 2)
    assert stage["foreign_bottom"].mean_gross_pooled == pytest.approx((0.02 + 0.01) / 2)

    # strength is the mirror image (highest strength == lowest foreign_net
    # in this fixture), so its top tertile should be the *worst* returns.
    assert stage["strength_top"].n_observations == 2
    assert stage["strength_top"].mean_gross_pooled == pytest.approx((0.02 + 0.01) / 2)
