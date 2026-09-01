from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateRow:
    ticker: str
    name: str
    sector: str
    provisional: bool
    volume_ratio: float | None
    rs: float | None
    stock_return: float | None
    location_score: int | None = None
    final_state: str | None = None
    entry_eligible: bool | None = None
    vetoes: list[str] = field(default_factory=list)
    breakout_entry_price: float | None = None
    breakout_rr: float | None = None


def _latest_decision_by_symbol(
    location_decisions: list[dict],
) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for decision in location_decisions:
        symbol = str(decision.get("symbol", ""))
        if not symbol:
            continue
        current = latest.get(symbol)
        if current is None:
            latest[symbol] = decision
            continue
        if str(decision.get("evaluated_at", "")) >= str(current.get("evaluated_at", "")):
            latest[symbol] = decision
    return latest


def build_candidate_board(
    *,
    filter_rows: list[dict],
    rs_rows: list[dict],
    location_decisions: list[dict] | None = None,
) -> list[CandidateRow]:
    """Rank today's observation candidates.

    Membership is decided solely by the stage-1 monthly10/weekly5 recovery
    filter (final_spec ch.0, an immutable contract) -- a symbol that failed
    it never appears here regardless of how strong its relative strength is.
    Ordering within the survivors is by relative strength, the strongest
    quantity this system actually computes for every symbol.

    This is deliberately NOT a buy-probability ranking. final_spec ch.2
    excludes Probability Score and Expected Value until real win-rate data
    exists, and the pattern-probability scanner currently reports PASS for
    zero symbols. Rows carry the evidence that was actually measured and
    leave everything unmeasured as None.
    """
    rs_by_ticker = {str(row.get("ticker", "")): row for row in rs_rows}
    decisions = _latest_decision_by_symbol(location_decisions or [])

    board: list[CandidateRow] = []
    for row in filter_rows:
        ticker = str(row.get("ticker", ""))
        rs_row = rs_by_ticker.get(ticker, {})
        decision = decisions.get(ticker, {})
        location_score = decision.get("location_score")
        board.append(
            CandidateRow(
                ticker=ticker,
                name=str(row.get("name", "")),
                sector=str(row.get("sector", "")),
                provisional=bool(row.get("provisional", False)),
                volume_ratio=row.get("volume_ratio"),
                rs=rs_row.get("rs"),
                stock_return=rs_row.get("stock_return"),
                location_score=int(location_score) if location_score is not None else None,
                final_state=decision.get("final_state"),
                entry_eligible=decision.get("entry_eligible"),
                vetoes=list(decision.get("vetoes", [])),
                breakout_entry_price=decision.get("breakout_entry_price"),
                breakout_rr=decision.get("breakout_rr"),
            )
        )

    # RS-less survivors sort last rather than being dropped or given a fake 0.
    board.sort(key=lambda row: (row.rs is None, -(row.rs or 0.0)))
    return board
