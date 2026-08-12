from lat5.leader_score import MarketLeaderInput, rank_market_leaders


def test_rank_market_leaders_scores_trading_value_more_than_rise_rate():
    rows = [
        MarketLeaderInput("A", "A", "KOSPI", "semi", 1000.0, 5.0),
        MarketLeaderInput("B", "B", "KOSPI", "semi", 800.0, 20.0),
        MarketLeaderInput("C", "C", "KOSPI", "bio", 100.0, 30.0),
    ]

    ranked = rank_market_leaders(rows)

    assert [item.ticker for item in ranked] == ["A", "B", "C"]
    assert ranked[0].leader_score > ranked[1].leader_score
    assert ranked[0].trading_value_rank == 1
    assert ranked[0].rise_rate_rank == 3


def test_rank_market_leaders_keeps_kospi_and_kosdaq_rankings_separate():
    rows = [
        MarketLeaderInput("K1", "K1", "KOSPI", "semi", 100.0, 10.0),
        MarketLeaderInput("Q1", "Q1", "KOSDAQ", "bio", 100.0, 10.0),
    ]

    ranked = rank_market_leaders(rows)

    assert sorted((item.ticker, item.trading_value_rank, item.rise_rate_rank) for item in ranked) == [
        ("K1", 1, 1),
        ("Q1", 1, 1),
    ]


def test_rank_market_leaders_rejects_non_positive_rise_as_candidate():
    rows = [
        MarketLeaderInput("UP", "UP", "KOSPI", "semi", 1000.0, 2.0),
        MarketLeaderInput("DOWN", "DOWN", "KOSPI", "semi", 2000.0, -1.0),
    ]

    ranked = rank_market_leaders(rows)

    assert [item.ticker for item in ranked] == ["UP"]
