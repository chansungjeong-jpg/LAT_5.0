from lat5.scoring import (
    MetricScore,
    classify_sector,
    daily_trend,
    execution_strength_points,
    foreign_flow_points,
    price_trend_points,
    turnover_points,
)


def test_daily_trend_distinguishes_strong_pullback_and_reject():
    assert daily_trend(105, 100, 95) == "STRONG"
    assert daily_trend(97, 100, 95) == "PULLBACK"
    assert daily_trend(94, 100, 95) == "REJECT"
    assert daily_trend(105, 94, 95) == "REJECT"
    assert daily_trend(None, 100, 95) == "UNKNOWN"


def test_price_trend_points_follow_daily_state():
    assert price_trend_points(105, 100, 95).points == 30
    assert price_trend_points(97, 100, 95).points == 15
    assert price_trend_points(94, 100, 95).points == 0
    assert not price_trend_points(None, 100, 95).known


def test_turnover_points_use_confirmed_30_point_bands():
    cases = [
        (0.79, 0),
        (0.80, 5),
        (1.00, 10),
        (1.20, 15),
        (1.50, 20),
        (2.00, 30),
    ]
    for ratio, expected in cases:
        assert turnover_points(ratio).points == expected


def test_execution_strength_points_use_25_point_bands():
    cases = [(89.9, 0), (90, 5), (100, 10), (110, 15), (120, 20), (140, 25)]
    for strength, expected in cases:
        assert execution_strength_points(strength).points == expected


def test_foreign_flow_points_use_reduced_15_point_weight():
    cases = [(-0.1, 0), (0.1, 3), (0.5, 6), (1.0, 9), (2.0, 12), (3.0, 15)]
    for percent, expected in cases:
        assert foreign_flow_points(percent).points == expected


def test_sector_classification_uses_score_bounds_for_missing_data():
    known_buy = [
        MetricScore(30, 30),
        MetricScore(20, 30),
        MetricScore(20, 25),
        MetricScore.unknown(15),
    ]
    result = classify_sector(known_buy, valid_members=7, total_members=10)
    assert result.status == "BUY"
    assert (result.score_lower, result.score_upper) == (70, 85)

    uncertain = [
        MetricScore(30, 30),
        MetricScore(20, 30),
        MetricScore.unknown(25),
        MetricScore(3, 15),
    ]
    assert classify_sector(uncertain, 7, 10).status == "DATA_UNKNOWN"

    all_known_watch = [
        MetricScore(15, 30),
        MetricScore(20, 30),
        MetricScore(15, 25),
        MetricScore(6, 15),
    ]
    assert classify_sector(all_known_watch, 7, 10).status == "WATCH"


def test_sector_requires_three_members_and_seventy_percent_coverage():
    perfect = [
        MetricScore(30, 30),
        MetricScore(30, 30),
        MetricScore(25, 25),
        MetricScore(15, 15),
    ]
    assert classify_sector(perfect, valid_members=2, total_members=3).status == "DATA_UNKNOWN"
    assert classify_sector(perfect, valid_members=6, total_members=10).status == "DATA_UNKNOWN"
