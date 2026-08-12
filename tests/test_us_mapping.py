from lat5.us_mapping import (
    US10Y_MARKET_INDICATOR,
    mappings_for,
    mapping_registry,
)


def test_company_mapping_returns_domestic_candidates_for_us_reference():
    mapping = mappings_for("MU")

    assert mapping is not None
    assert "000660" in mapping.kr_tickers
    assert mapping.flow == "US_AI_FLOW"


def test_mapping_registry_contains_requested_defense_biotech_and_battery_flows():
    flows = {item.flow for item in mapping_registry()}

    assert {"US_DEFENSE_FLOW", "US_BIOTECH_FLOW", "US_BATTERY_FLOW"} <= flows


def test_unknown_reference_does_not_fallback_to_a_domestic_stock():
    assert mappings_for("UNKNOWN") is None


def test_ten_year_treasury_is_market_context_not_sector_flow():
    assert US10Y_MARKET_INDICATOR.symbol == "US10Y"
    assert US10Y_MARKET_INDICATOR.flow == "US_MARKET_FLOW"
    assert US10Y_MARKET_INDICATOR.kr_tickers == ()
