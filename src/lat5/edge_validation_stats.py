"""Comparison-stage statistics for edge_validation.py.

Kept in a separate module from the point-in-time calculators so the
"what did we measure" (edge_validation.py) and "how do we summarize it"
(this file) concerns stay easy to test independently.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import pandas as pd

from lat5.edge_validation import OutcomeResult, TickerDayRecord


@dataclass(frozen=True)
class DailyMean:
    eval_day: pd.Timestamp
    n: int
    mean_gross: float
    mean_net: float


@dataclass(frozen=True)
class GroupStats:
    n_observations: int
    n_eval_days: int
    mean_gross_pooled: float | None  # equal weight per stock-day
    mean_gross_daily_avg: float | None  # equal weight per eval day, then averaged
    mean_net_pooled: float | None
    median_gross_pooled: float | None
    positive_rate_pooled: float | None
    mean_mfe_pooled: float | None
    mean_mae_pooled: float | None
    per_day: tuple[DailyMean, ...]


_EMPTY_GROUP_STATS = GroupStats(0, 0, None, None, None, None, None, None, None, ())


def _mature_outcomes(
    records: list[TickerDayRecord], hold_days: int, outcome_attr: str = "outcomes"
) -> list[tuple[TickerDayRecord, OutcomeResult]]:
    out = []
    for record in records:
        outcome = getattr(record, outcome_attr).get(hold_days)
        if outcome is not None and outcome.status == "MATURE":
            out.append((record, outcome))
    return out


def summarize_group(
    records: list[TickerDayRecord], hold_days: int, outcome_attr: str = "outcomes"
) -> GroupStats:
    """`outcome_attr` selects which fill rule's outcomes to summarize:
    "outcomes" (next-session open entry -> H-day close exit, production
    rule) or "outcomes_close_to_open" (signal-day close entry -> H-day open
    exit, the priority-1 A/B candidate -- see edge_validation.py)."""
    matured = _mature_outcomes(records, hold_days, outcome_attr)
    if not matured:
        return _EMPTY_GROUP_STATS

    gross = pd.Series([outcome.gross_return for _, outcome in matured], dtype=float)
    net = pd.Series([outcome.net_return for _, outcome in matured], dtype=float)
    mfe = pd.Series([outcome.mfe for _, outcome in matured], dtype=float)
    mae = pd.Series([outcome.mae for _, outcome in matured], dtype=float)

    by_day: dict[pd.Timestamp, list[float]] = {}
    by_day_net: dict[pd.Timestamp, list[float]] = {}
    for record, outcome in matured:
        by_day.setdefault(record.eval_day, []).append(outcome.gross_return)
        by_day_net.setdefault(record.eval_day, []).append(outcome.net_return)
    per_day = tuple(
        DailyMean(
            day,
            len(values),
            sum(values) / len(values),
            sum(by_day_net[day]) / len(by_day_net[day]),
        )
        for day, values in sorted(by_day.items())
    )
    daily_avg_gross = sum(d.mean_gross for d in per_day) / len(per_day) if per_day else None

    return GroupStats(
        n_observations=len(matured),
        n_eval_days=len(per_day),
        mean_gross_pooled=float(gross.mean()),
        mean_gross_daily_avg=daily_avg_gross,
        mean_net_pooled=float(net.mean()),
        median_gross_pooled=float(gross.median()),
        positive_rate_pooled=float((gross > 0).mean()),
        mean_mfe_pooled=float(mfe.mean()),
        mean_mae_pooled=float(mae.mean()),
        per_day=per_day,
    )


def independent_block_count(
    eval_days: list[pd.Timestamp], hold_days: int, calendar: list[pd.Timestamp]
) -> int:
    """Greedy count of non-overlapping evaluation-day blocks for a given
    holding period, using calendar position as the overlap ruler. Two
    evaluation days whose holding windows would share any session are
    treated as one block -- see design doc section 8.
    """
    if not eval_days:
        return 0
    position = {day: idx for idx, day in enumerate(calendar)}
    ordered = sorted(d for d in eval_days if d in position)
    blocks = 0
    next_free_position = -1
    for day in ordered:
        pos = position[day]
        if pos > next_free_position:
            blocks += 1
            next_free_position = pos + hold_days
    return blocks


def rank_top_n(candidates: list[tuple[str, float]], n: int) -> set[str]:
    """Top n tickers by value descending, ties broken by ticker code ascending."""
    ordered = sorted(candidates, key=lambda pair: (-pair[1], pair[0]))
    return {ticker for ticker, _ in ordered[:n]}


def split_tertiles(candidates: list[tuple[str, float]]) -> tuple[set[str], set[str], set[str]]:
    """Top/mid/bottom thirds by value descending, ties broken by ticker code."""
    ordered = [ticker for ticker, _ in sorted(candidates, key=lambda pair: (-pair[1], pair[0]))]
    n = len(ordered)
    if n == 0:
        return set(), set(), set()
    base, extra = divmod(n, 3)
    sizes = [base + (1 if i < extra else 0) for i in range(3)]
    top = set(ordered[: sizes[0]])
    mid = set(ordered[sizes[0] : sizes[0] + sizes[1]])
    bottom = set(ordered[sizes[0] + sizes[1] :])
    return top, mid, bottom


def location_bin(score: int) -> str:
    if score < 40:
        return "0-39"
    if score < 60:
        return "40-59"
    if score < 80:
        return "60-79"
    return "80-100"


def veto_cooccurrence(vetoes_by_record: list[tuple[str, ...]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for vetoes in vetoes_by_record:
        counts.update(vetoes)
    return dict(counts)


def top_n_for_rs(recovery_pass_with_rs: list[tuple[str, float]]) -> int:
    return math.ceil(len(recovery_pass_with_rs) * 0.3)


# ---------------------------------------------------------------------------
# Full comparison build (c-handoff.md "단계별 비교")
# ---------------------------------------------------------------------------


def build_comparisons(
    records: list[TickerDayRecord],
    eval_days: list[pd.Timestamp],
    calendar: list[pd.Timestamp],
    holds: tuple[int, ...],
    rs_days: int,
    outcome_attr: str = "outcomes",
) -> dict[str, object]:
    """Rank RS / location score within each evaluation day's recovery-pass
    cohort (a cross-sectional ranking), then pool the resulting group
    membership across days before summarizing outcomes. Ranking must happen
    per day -- pooling raw RS/location values across days first would let a
    high-RS day swamp a low-RS day instead of comparing each day's own
    survivors against each other.
    """
    groups: dict[str, set[tuple[pd.Timestamp, str]]] = {
        name: set()
        for name in (
            "recovery_pass", "recovery_fail",
            "rs_top", "rs_mid", "rs_bottom", "rs_top30",
            "loc_0_39", "loc_40_59", "loc_60_79", "loc_80_100", "loc_top_n",
            "rr_pass", "rr_blocked", "rr_unmeasured",
            "foreign_top", "foreign_mid", "foreign_bottom",
            "strength_top", "strength_mid", "strength_bottom",
            "rsi_recovery", "rsi_no_recovery",
        )
    }
    veto_lists: list[tuple[str, ...]] = []
    rs_top30_n_by_day: dict[pd.Timestamp, int] = {}

    for day in eval_days:
        cohort = [r for r in records if r.eval_day == day and r.recovery.passed]
        for record in cohort:
            groups["recovery_pass"].add((day, record.ticker))

        rs_known = [(r.ticker, r.rs) for r in cohort if r.rs is not None]
        top_rs, mid_rs, bottom_rs = split_tertiles(rs_known)
        n_top30 = top_n_for_rs(rs_known)
        rs_top30_n_by_day[day] = n_top30
        top30 = rank_top_n(rs_known, n_top30) if rs_known else set()
        for ticker in top_rs:
            groups["rs_top"].add((day, ticker))
        for ticker in mid_rs:
            groups["rs_mid"].add((day, ticker))
        for ticker in bottom_rs:
            groups["rs_bottom"].add((day, ticker))
        for ticker in top30:
            groups["rs_top30"].add((day, ticker))

        loc_known = [(r.ticker, r.location.score) for r in cohort if r.location.score is not None]
        for ticker, score in loc_known:
            bin_key = "loc_" + location_bin(score).replace("-", "_")
            groups[bin_key].add((day, ticker))
        top_loc = rank_top_n(loc_known, n_top30) if loc_known else set()
        for ticker in top_loc:
            groups["loc_top_n"].add((day, ticker))

        foreign_known = [
            (r.ticker, r.flow.foreign_net_cum) for r in cohort if r.flow.foreign_net_cum is not None
        ]
        top_foreign, mid_foreign, bottom_foreign = split_tertiles(foreign_known)
        for ticker in top_foreign:
            groups["foreign_top"].add((day, ticker))
        for ticker in mid_foreign:
            groups["foreign_mid"].add((day, ticker))
        for ticker in bottom_foreign:
            groups["foreign_bottom"].add((day, ticker))

        strength_known = [
            (r.ticker, r.flow.strength_mean) for r in cohort if r.flow.strength_mean is not None
        ]
        top_strength, mid_strength, bottom_strength = split_tertiles(strength_known)
        for ticker in top_strength:
            groups["strength_top"].add((day, ticker))
        for ticker in mid_strength:
            groups["strength_mid"].add((day, ticker))
        for ticker in bottom_strength:
            groups["strength_bottom"].add((day, ticker))

        rsi_known = [(r.ticker, r.rsi.signal) for r in cohort if r.rsi.signal is not None]
        for ticker, signal in rsi_known:
            groups["rsi_recovery" if signal else "rsi_no_recovery"].add((day, ticker))

        for record in cohort:
            if record.location.score is None:
                continue
            if not record.location.rr_known:
                groups["rr_unmeasured"].add((day, record.ticker))
            elif "RR_TOO_LOW" in record.location.vetoes:
                groups["rr_blocked"].add((day, record.ticker))
                veto_lists.append(record.location.vetoes)
            else:
                groups["rr_pass"].add((day, record.ticker))

    for record in records:
        if not record.recovery.passed:
            groups["recovery_fail"].add((record.eval_day, record.ticker))

    def _filtered(key: str) -> list[TickerDayRecord]:
        keys = groups[key]
        return [r for r in records if (r.eval_day, r.ticker) in keys]

    result: dict[str, object] = {
        "rs_days": rs_days,
        "eval_day_count": len(eval_days),
        "rs_top30_n_by_day": {str(day.date()): n for day, n in rs_top30_n_by_day.items()},
        "rr_veto_cooccurrence": veto_cooccurrence(veto_lists),
    }
    group_labels = list(groups.keys())
    for hold_days in holds:
        stage: dict[str, object] = {
            "overall_universe": summarize_group(records, hold_days, outcome_attr)
        }
        for label in group_labels:
            stage[label] = summarize_group(_filtered(label), hold_days, outcome_attr)
        stage["independent_blocks_recovery_pass"] = independent_block_count(
            eval_days, hold_days, calendar
        )
        result[f"hold_{hold_days}"] = stage
    return result
