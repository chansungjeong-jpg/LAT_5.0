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
        daily_ma_reaction_score=20,
        daily_ma_reaction_state="SMA60_UPWARD_CROSS_STRONG_BULL",
    )
    values.update(overrides)
    return LocationInputs(**values)


def test_location_score_gives_volume_the_largest_weight_and_can_buy():
    result = score_location(_strong_inputs())

    assert result.state == "BUY"
    assert result.score == 100
    assert result.components["volume"] == 30
    assert result.components["m60_location"] == 20
    assert result.components["weekly_trend"] == 10
    assert result.components["daily_trend"] == 5


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


def test_daily_ma_reaction_is_a_twenty_point_component():
    result = score_location(_strong_inputs(daily_ma_reaction_score=20))

    assert result.components["daily_ma_reaction"] == 20


def test_daily_ma_reaction_does_not_exceed_total_component_cap():
    result = score_location(_strong_inputs(daily_ma_reaction_score=99))

    assert result.components["daily_ma_reaction"] == 20


def test_daily_ma_reaction_unknown_fails_closed():
    result = score_location(
        _strong_inputs(daily_ma_reaction_score=20, daily_ma_reaction_state="UNKNOWN")
    )

    assert result.state == "REJECT"
    assert result.components["daily_ma_reaction"] == 0
    assert "daily_ma_reaction" in result.unknown_fields
    assert "DAILY_MA_REACTION_UNKNOWN" in result.vetoes


def test_missing_daily_ma_reaction_score_fails_closed():
    result = score_location(
        _strong_inputs(
            daily_ma_reaction_score=None,
            daily_ma_reaction_state="SMA60_UPWARD_CROSS_STRONG_BULL",
        )
    )

    assert result.state == "REJECT"
    assert result.components["daily_ma_reaction"] == 0
    assert "daily_ma_reaction" in result.unknown_fields
    assert "DAILY_MA_REACTION_UNKNOWN" in result.vetoes


def test_sma5_break_can_make_watch_but_is_not_hard_reject_by_itself():
    result = score_location(
        _strong_inputs(
            volume_ratio=1.3,
            daily_ma_reaction_score=-4,
            daily_ma_reaction_state="SMA5_CLOSE_BREAK",
        )
    )

    assert result.state == "WATCH"
    assert result.components["daily_ma_reaction"] == -4
    assert "DAILY_MA_HARD_BLOCK" not in result.vetoes


def test_sma20_close_break_is_a_daily_ma_hard_block():
    result = score_location(
        _strong_inputs(
            daily_ma_reaction_score=-8,
            daily_ma_reaction_state="SMA20_CLOSE_BREAK",
        )
    )

    assert result.state == "REJECT"
    assert result.components["daily_ma_reaction"] == -8
    assert "DAILY_MA_HARD_BLOCK" in result.vetoes


def test_golden_cross_is_not_a_standalone_location_bonus():
    without = score_location(_strong_inputs(golden_cross_ok=False))
    with_cross = score_location(_strong_inputs(golden_cross_ok=True))

    assert with_cross.score == without.score
    assert "golden_cross" not in with_cross.components
