from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from lat5.kiwoom_client import KiwoomApiError, KiwoomTokenError


class SchemaMismatch(ValueError):
    pass


def _number(value: Any, *, absolute: bool = False) -> float:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise SchemaMismatch(f"invalid numeric value: {value!r}") from exc
    return abs(number) if absolute else number


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise SchemaMismatch(f"missing or invalid {key}")
    if any(not isinstance(row, dict) for row in rows):
        raise SchemaMismatch(f"invalid row in {key}")
    return rows


def _date(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise SchemaMismatch(f"invalid date: {value!r}") from exc


def _datetime(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").isoformat()
    except ValueError as exc:
        raise SchemaMismatch(f"invalid datetime: {value!r}") from exc


def parse_daily(ticker: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = []
    for row in _rows(payload, "stk_dt_pole_chart_qry"):
        close = _number(row.get("cur_prc"), absolute=True)
        volume = int(_number(row.get("trde_qty"), absolute=True))
        parsed.append(
            {
                "ticker": ticker,
                "date": _date(row.get("dt")),
                "open": _number(row.get("open_pric"), absolute=True),
                "high": _number(row.get("high_pric"), absolute=True),
                "low": _number(row.get("low_pric"), absolute=True),
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return parsed


def parse_minutes(
    ticker: str, payload: dict[str, Any], interval: str = "5"
) -> list[dict[str, Any]]:
    parsed = []
    for row in _rows(payload, "stk_min_pole_chart_qry"):
        close = _number(row.get("cur_prc"), absolute=True)
        volume = int(_number(row.get("trde_qty"), absolute=True))
        parsed.append(
            {
                "ticker": ticker,
                "datetime": _datetime(row.get("cntr_tm")),
                "interval": interval,
                "open": _number(row.get("open_pric"), absolute=True),
                "high": _number(row.get("high_pric"), absolute=True),
                "low": _number(row.get("low_pric"), absolute=True),
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return parsed


def parse_strength(
    ticker: str, payload: dict[str, Any], trade_date: str
) -> list[dict[str, Any]]:
    parsed = []
    for row in _rows(payload, "cntr_str_tm"):
        try:
            observed_at = datetime.strptime(
                f"{trade_date} {row.get('cntr_tm')}", "%Y-%m-%d %H%M%S"
            ).isoformat()
        except ValueError as exc:
            raise SchemaMismatch(f"invalid cntr_tm: {row.get('cntr_tm')!r}") from exc
        parsed.append(
            {
                "ticker": ticker,
                "datetime": observed_at,
                "strength": _number(row.get("cntr_str")),
            }
        )
    return parsed


def parse_foreign_flow(ticker: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "date": _date(row.get("dt")),
            "foreign_net_thousand": _number(row.get("frgnr_invsr")),
        }
        for row in _rows(payload, "stk_invsr_orgn")
    ]


def collect_symbol(
    client,
    store,
    run_id: int,
    ticker: str,
    base_date: str,
) -> dict[str, int]:
    trade_date = _date(base_date)
    requests: list[tuple[str, str, dict[str, str], Callable]] = [
        (
            "ka10081",
            "/api/dostk/chart",
            {"stk_cd": ticker, "base_dt": base_date, "upd_stkpc_tp": "1"},
            lambda payload: store.save_daily(run_id, parse_daily(ticker, payload)),
        ),
        (
            "ka10080",
            "/api/dostk/chart",
            {"stk_cd": ticker, "tic_scope": "5", "upd_stkpc_tp": "1"},
            lambda payload: store.save_minutes(run_id, parse_minutes(ticker, payload)),
        ),
        (
            "ka10046",
            "/api/dostk/mrkcond",
            {"stk_cd": ticker},
            lambda payload: store.save_strength(
                run_id, parse_strength(ticker, payload, trade_date)
            ),
        ),
        (
            "ka10059",
            "/api/dostk/stkinfo",
            {
                "dt": base_date,
                "stk_cd": ticker,
                "amt_qty_tp": "1",
                "trde_tp": "0",
                "unit_tp": "1000",
            },
            lambda payload: store.save_foreign_flow(
                run_id, parse_foreign_flow(ticker, payload)
            ),
        ),
    ]
    result = {"success": 0, "errors": 0}
    for api_id, path, body, save in requests:
        try:
            for page in client.post_pages(api_id, path, body):
                store.save_raw_page(run_id, ticker, page)
                save(page.payload)
            result["success"] += 1
        except KiwoomTokenError:
            raise
        except SchemaMismatch as exc:
            store.record_error(run_id, ticker, api_id, "SCHEMA_MISMATCH", str(exc))
            result["errors"] += 1
        except KiwoomApiError as exc:
            store.record_error(run_id, ticker, api_id, "API_ERROR", str(exc))
            result["errors"] += 1
    return result


def collect_watchlist(
    client,
    store,
    run_id: int,
    tickers: Iterable[str],
    base_date: str,
) -> dict[str, int]:
    symbols = list(dict.fromkeys(tickers))
    success_symbols = 0
    api_errors = 0
    for ticker in symbols:
        result = collect_symbol(client, store, run_id, ticker, base_date)
        api_errors += result["errors"]
        if result["errors"] == 0:
            success_symbols += 1
    return {
        "symbols": len(symbols),
        "success_symbols": success_symbols,
        "api_errors": api_errors,
    }
