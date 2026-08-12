import pytest

from lat5.collector import (
    SchemaMismatch,
    collect_symbol,
    collect_watchlist,
    parse_daily,
    parse_foreign_flow,
    parse_minutes,
    parse_strength,
)
from lat5.kiwoom_client import ApiPage, KiwoomTokenError


def test_parse_daily_normalizes_signed_prices_and_commas():
    payload = {
        "stk_dt_pole_chart_qry": [
            {
                "dt": "20260808",
                "open_pric": "+70,000",
                "high_pric": "+71,000",
                "low_pric": "-69,000",
                "cur_prc": "+70,500",
                "trde_qty": "1,234",
            }
        ]
    }

    assert parse_daily("005930", payload) == [
        {
            "ticker": "005930",
            "date": "2026-08-08",
            "open": 70000.0,
            "high": 71000.0,
            "low": 69000.0,
            "close": 70500.0,
            "volume": 1234,
            "amount": 86997000.0,
        }
    ]


def test_parse_minutes_normalizes_timestamp_and_amount():
    payload = {
        "stk_min_pole_chart_qry": [
            {
                "cntr_tm": "20260808152500",
                "open_pric": "+70,000",
                "high_pric": "+70,500",
                "low_pric": "-69,900",
                "cur_prc": "+70,300",
                "trde_qty": "100",
            }
        ]
    }

    assert parse_minutes("005930", payload) == [
        {
            "ticker": "005930",
            "datetime": "2026-08-08T15:25:00",
            "interval": "5",
            "open": 70000.0,
            "high": 70500.0,
            "low": 69900.0,
            "close": 70300.0,
            "volume": 100,
            "amount": 7030000.0,
        }
    ]


def test_parse_strength_combines_trade_date_with_intraday_time():
    payload = {"cntr_str_tm": [{"cntr_tm": "152500", "cntr_str": "123.45"}]}

    assert parse_strength("005930", payload, trade_date="2026-08-08") == [
        {
            "ticker": "005930",
            "datetime": "2026-08-08T15:25:00",
            "strength": 123.45,
        }
    ]


def test_parse_strength_fails_closed_on_schema_mismatch():
    with pytest.raises(SchemaMismatch, match="cntr_str_tm"):
        parse_strength("005930", {"unexpected": []}, trade_date="2026-08-08")


def test_parse_foreign_flow_preserves_buy_sell_sign():
    payload = {
        "stk_invsr_orgn": [
            {"dt": "20260808", "frgnr_invsr": "-1,250"},
            {"dt": "20260807", "frgnr_invsr": "+2,500"},
        ]
    }

    assert parse_foreign_flow("005930", payload) == [
        {"ticker": "005930", "date": "2026-08-08", "foreign_net_thousand": -1250.0},
        {"ticker": "005930", "date": "2026-08-07", "foreign_net_thousand": 2500.0},
    ]


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def post_pages(self, api_id, path, body):
        self.calls.append((api_id, path, body))
        value = self.payloads[api_id]
        if isinstance(value, Exception):
            raise value
        yield ApiPage(api_id, 1, value, "N", "")


class EventStore:
    def __init__(self):
        self.events = []

    def save_raw_page(self, run_id, ticker, page):
        self.events.append(("raw", page.api_id))

    def save_daily(self, run_id, rows):
        self.events.append(("parsed", "ka10081"))

    def save_minutes(self, run_id, rows):
        self.events.append(("parsed", "ka10080"))

    def save_strength(self, run_id, rows):
        self.events.append(("parsed", "ka10046"))

    def save_foreign_flow(self, run_id, rows):
        self.events.append(("parsed", "ka10059"))

    def record_error(self, run_id, ticker, api_id, error_code, message):
        self.events.append(("error", api_id, error_code))


def test_collect_symbol_preserves_raw_first_and_continues_after_schema_error():
    client = FakeClient(
        {
            "ka10081": {"stk_dt_pole_chart_qry": []},
            "ka10080": {"stk_min_pole_chart_qry": []},
            "ka10046": {"unexpected": []},
            "ka10059": {"stk_invsr_orgn": []},
        }
    )
    store = EventStore()

    result = collect_symbol(client, store, 7, "005930", base_date="20260808")

    assert result == {"success": 3, "errors": 1}
    assert [call[:2] for call in client.calls] == [
        ("ka10081", "/api/dostk/chart"),
        ("ka10080", "/api/dostk/chart"),
        ("ka10046", "/api/dostk/mrkcond"),
        ("ka10059", "/api/dostk/stkinfo"),
    ]
    for api_id in ("ka10081", "ka10080", "ka10046", "ka10059"):
        raw_at = store.events.index(("raw", api_id))
        later = [i for i, event in enumerate(store.events) if event[1] == api_id and event[0] != "raw"]
        assert later and raw_at < later[0]
    assert ("error", "ka10046", "SCHEMA_MISMATCH") in store.events


def test_collect_symbol_propagates_token_error_to_block_entire_run():
    client = FakeClient({"ka10081": KiwoomTokenError("8005 token expired")})

    with pytest.raises(KiwoomTokenError):
        collect_symbol(client, EventStore(), 7, "005930", base_date="20260808")


def test_collect_watchlist_deduplicates_tickers_and_aggregates_symbol_results():
    client = FakeClient(
        {
            "ka10081": {"stk_dt_pole_chart_qry": []},
            "ka10080": {"stk_min_pole_chart_qry": []},
            "ka10046": {"cntr_str_tm": []},
            "ka10059": {"stk_invsr_orgn": []},
        }
    )

    result = collect_watchlist(
        client, EventStore(), 7, ["005930", "005930"], base_date="20260808"
    )

    assert result == {"symbols": 1, "success_symbols": 1, "api_errors": 0}
    assert len(client.calls) == 4
