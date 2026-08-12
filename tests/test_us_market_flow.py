from datetime import date

from lat5.us_market_flow import (
    MarketGateRules,
    USMarketObservation,
    evaluate_market_gate,
    aggregate_company_flows,
)


def _obs(symbol, change, as_of=date(2026, 8, 12)):
    return USMarketObservation(symbol, as_of, 100.0, 100.0 * (1 + change), as_of)


def test_market_gate_uses_indices_and_us10y_not_company_mappings():
    observations = [
        _obs("SPY", 0.01), _obs("QQQ", 0.02), _obs("IWM", 0.01),
        _obs("DIA", 0.005), _obs("VIX", -0.05), _obs("US10Y", -0.01),
    ]

    decision = evaluate_market_gate(
        observations,
        as_of=date(2026, 8, 12),
        rules=MarketGateRules(min_positive_indices=3),
    )

    assert decision.state == "BUY"
    assert decision.flow == "US_MARKET_FLOW"
    assert decision.us10y_symbol == "US10Y"


def test_market_gate_is_unknown_when_required_context_is_stale():
    observations = [_obs("SPY", 0.01, date(2026, 8, 1))]

    decision = evaluate_market_gate(
        observations,
        as_of=date(2026, 8, 12),
        rules=MarketGateRules(max_age_days=2),
    )

    assert decision.state == "UNKNOWN"
    assert "STALE_OR_MISSING_US_CONTEXT" in decision.reasons


def test_company_flows_are_separate_from_market_gate():
    observations = [_obs("MU", 0.04), _obs("NVDA", 0.02), _obs("RUN", -0.01)]

    flows = aggregate_company_flows(observations)

    assert flows["US_AI_FLOW"].direction == "POSITIVE"
    assert flows["US_SOLAR_FLOW"].direction == "NEGATIVE"
    assert "US_MARKET_FLOW" not in flows
