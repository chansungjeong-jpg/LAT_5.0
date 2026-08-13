from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any


def _score(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def rank_location_decisions(
    decisions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rank location decisions without changing their eligibility semantics.

    Eligible decisions with known scores come first, sorted by descending
    location score. Ineligible or score-unknown decisions remain visible for
    observability but receive no position rank and are placed after ranked
    candidates. The function never fabricates a score.
    """
    rows = [dict(decision) for decision in decisions]
    indexed = list(enumerate(rows))

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, float, int]:
        index, row = item
        score = _score(row.get("location_score"))
        eligible = row.get("entry_eligible") is True
        known_eligible = eligible and score is not None
        return (
            0 if known_eligible else 1,
            0 if eligible else 1,
            -(score if score is not None else float("-inf")),
            index,
        )

    ranked: list[dict[str, Any]] = []
    position_rank = 0
    for _, row in sorted(indexed, key=sort_key):
        if row.get("entry_eligible") is True and _score(row.get("location_score")) is not None:
            position_rank += 1
            row["position_rank"] = position_rank
        else:
            row["position_rank"] = None
        ranked.append(row)
    return ranked


__all__ = ["rank_location_decisions"]
