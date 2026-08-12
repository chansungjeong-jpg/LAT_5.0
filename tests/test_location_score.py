from lat5.location_score import LocationInputs, score_location


def _strong_inputs(**overrides):
    values = dict(
        market_state="BUY",
        sector_score=75.0,
        leader_ok=True,
        weekly_trend_ok=True,
        daily_trend_ok=True,
        recent_5d_bullish_count=5,
        price=105.0,
        ema60=100.0,
        ema120=95.0,
        m60_slope_pct=0.01,
        volume_ratio=2.0,
        m5_distance_pct=0.01,
        daily_distance_pct=0.05,
        supply_distance_pct=0.08,
        rr=2.0,
    )
    values.update(overrides)
    return LocationInputs(**values)


def test_location_score_gives_volume_the_largest_weight_and_can_buy():
    result = score_location(_strong_inputs())

    assert result.state == "BUY"
    assert result.score == 100
    assert result.components["volume"] == 30


def test_location_score_blocks_buy_when_distance_is_overheated():
    result = score_location(_strong_inputs(m5_distance_pct=0.031))

    assert result.state == "WATCH"
    assert "M5_DISTANCE_OVERHEATED" in result.vetoes


def test_location_score_rejects_weak_market_sector_or_rr():
    assert score_location(_strong_inputs(market_state="RISK_OFF")).state == "REJECT"
    assert score_location(_strong_inputs(sector_score=59.9)).state == "REJECT"
    assert score_location(_strong_inputs(rr=1.49)).state == "REJECT"


def test_location_score_rejects_missing_required_inputs():
    result = score_location(_strong_inputs(volume_ratio=None))

    assert result.state == "REJECT"
    assert "volume_ratio" in result.unknown_fields


def test_golden_cross_is_only_a_small_confirmation_bonus():
    without = score_location(_strong_inputs(daily_trend_ok=False, golden_cross_ok=False))
    with_cross = score_location(_strong_inputs(daily_trend_ok=False, golden_cross_ok=True))

    assert with_cross.score == without.score + 3
    assert with_cross.components["golden_cross"] == 3
