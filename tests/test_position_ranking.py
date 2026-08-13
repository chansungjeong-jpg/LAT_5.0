from lat5.position_ranking import rank_location_decisions


def test_rank_location_decisions_prioritizes_eligible_high_score_candidates():
    decisions = [
        {"symbol": "LOW", "location_score": 95, "entry_eligible": False},
        {"symbol": "HIGH", "location_score": 82, "entry_eligible": True},
        {"symbol": "MID", "location_score": 74, "entry_eligible": True},
    ]

    ranked = rank_location_decisions(decisions)

    assert [item["symbol"] for item in ranked] == ["HIGH", "MID", "LOW"]
    assert [item["position_rank"] for item in ranked] == [1, 2, None]


def test_rank_location_decisions_does_not_invent_missing_scores():
    decisions = [
        {"symbol": "UNKNOWN", "entry_eligible": True},
        {"symbol": "KNOWN", "location_score": 40, "entry_eligible": True},
    ]

    ranked = rank_location_decisions(decisions)

    assert [item["symbol"] for item in ranked] == ["KNOWN", "UNKNOWN"]
    assert ranked[-1]["position_rank"] is None
