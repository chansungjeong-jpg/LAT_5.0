from lat5.us_featured import USFeaturedInput, select_us_featured_stocks


def test_featured_selection_requires_positive_rise_and_uses_three_rankings():
    rows = [
        USFeaturedInput("NVDA", 0.10, 5.0, 900.0),
        USFeaturedInput("MU", 0.06, 4.0, 700.0),
        USFeaturedInput("RUN", 0.02, 2.0, 100.0),
        USFeaturedInput("LMT", -0.03, 9.0, 999.0),
    ]

    selected = select_us_featured_stocks(rows, top_n=2)

    assert [item.symbol for item in selected] == ["NVDA", "MU"]
    assert all(item.flow == "US_AI_FLOW" for item in selected)
    assert selected[0].featured_score > selected[1].featured_score


def test_featured_selection_ignores_unmapped_symbols():
    rows = [USFeaturedInput("UNKNOWN", 0.5, 100.0, 10000.0)]

    assert select_us_featured_stocks(rows, top_n=5) == ()


def test_featured_selection_rejects_invalid_top_n():
    try:
        select_us_featured_stocks([], top_n=0)
    except ValueError as exc:
        assert "top_n" in str(exc)
    else:
        raise AssertionError("expected ValueError")
