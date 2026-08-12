import pytest

from lat5.leader_collector import (
    parse_rise_rate_rows,
    parse_trading_value_rows,
    merge_leader_inputs,
)


def test_parse_official_trading_value_payload():
    rows = parse_trading_value_rows(
        {
            "trde_prica_upper": [
                {
                    "stk_cd": "005930",
                    "stk_nm": "삼성전자",
                    "flu_rt": "3.25",
                    "trde_prica": "1234567890",
                }
            ]
        },
        market="KOSPI",
    )

    assert rows[0].ticker == "005930"
    assert rows[0].market == "KOSPI"
    assert rows[0].trading_value == 1234567890
    assert rows[0].rise_rate == 3.25


def test_parse_official_rise_rate_payload_preserves_negative_rate():
    rows = parse_rise_rate_rows(
        {
            "pred_pre_flu_rt_upper": [
                {
                    "stk_cd": "000660",
                    "stk_nm": "SK하이닉스",
                    "flu_rt": "-1.50",
                }
            ]
        },
        market="KOSPI",
    )

    assert rows[0].ticker == "000660"
    assert rows[0].rise_rate == -1.5
    assert rows[0].trading_value is None


def test_merge_requires_both_metrics_and_rejects_unknown_market():
    trading = parse_trading_value_rows(
        {"trde_prica_upper": [{"stk_cd": "A", "stk_nm": "A", "trde_prica": "100"}]},
        market="KOSPI",
    )
    rising = parse_rise_rate_rows(
        {"pred_pre_flu_rt_upper": [{"stk_cd": "A", "stk_nm": "A", "flu_rt": "2"}]},
        market="KOSPI",
    )

    merged = merge_leader_inputs(trading, rising)
    assert merged[0].trading_value == 100
    assert merged[0].rise_rate == 2

    with pytest.raises(ValueError):
        parse_trading_value_rows({"trde_prica_upper": []}, market="NYSE")
