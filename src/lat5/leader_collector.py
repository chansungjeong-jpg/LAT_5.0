from __future__ import annotations

from typing import Any, Iterable

from lat5.leader_score import MarketLeaderInput
from lat5.leader_score import rank_market_leaders


class LeaderSchemaMismatch(ValueError):
    pass


_TRADING_VALUE_KEY = "trde_prica_upper"
_RISE_RATE_KEY = "pred_pre_flu_rt_upper"


def _number(value: Any, field: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise LeaderSchemaMismatch(f"invalid {field}: {value!r}") from exc


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    records = payload.get(key)
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise LeaderSchemaMismatch(f"missing or invalid {key}")
    return records


def _validate_market(market: str) -> None:
    if market not in {"KOSPI", "KOSDAQ"}:
        raise ValueError(f"unsupported market: {market!r}")


def _parse(
    payload: dict[str, Any],
    *,
    market: str,
    key: str,
    trading_value_required: bool,
) -> list[MarketLeaderInput]:
    _validate_market(market)
    parsed: list[MarketLeaderInput] = []
    for row in _rows(payload, key):
        ticker = str(row.get("stk_cd", "")).strip()
        name = str(row.get("stk_nm", "")).strip()
        if not ticker or not name:
            raise LeaderSchemaMismatch("ticker and name are required")
        raw_value = row.get("trde_prica")
        trading_value = (
            _number(raw_value, "trde_prica")
            if trading_value_required or raw_value is not None
            else None
        )
        raw_rise = row.get("flu_rt")
        rise_rate = _number(raw_rise, "flu_rt") if raw_rise is not None else None
        parsed.append(
            MarketLeaderInput(
                ticker=ticker,
                name=name,
                market=market,
                sector=None,
                trading_value=trading_value,
                rise_rate=rise_rate,
            )
        )
    return parsed


def parse_trading_value_rows(
    payload: dict[str, Any], *, market: str
) -> list[MarketLeaderInput]:
    return _parse(
        payload,
        market=market,
        key=_TRADING_VALUE_KEY,
        trading_value_required=True,
    )


def parse_rise_rate_rows(
    payload: dict[str, Any], *, market: str
) -> list[MarketLeaderInput]:
    return _parse(
        payload,
        market=market,
        key=_RISE_RATE_KEY,
        trading_value_required=False,
    )


def merge_leader_inputs(
    trading_rows: Iterable[MarketLeaderInput],
    rise_rows: Iterable[MarketLeaderInput],
) -> list[MarketLeaderInput]:
    merged: dict[tuple[str, str], MarketLeaderInput] = {}
    for row in trading_rows:
        if row.trading_value is not None:
            merged[(row.market, row.ticker)] = row
    for row in rise_rows:
        key = (row.market, row.ticker)
        existing = merged.get(key)
        if existing is None:
            continue
        merged[key] = MarketLeaderInput(
            ticker=existing.ticker,
            name=existing.name,
            market=existing.market,
            sector=existing.sector,
            trading_value=existing.trading_value,
            rise_rate=row.rise_rate,
        )
    return [row for row in merged.values() if row.rise_rate is not None]


def collect_market_leaders(
    client,
    store,
    run_id: int,
    *,
    as_of: str,
    markets: Iterable[tuple[str, str]] = (("KOSPI", "001"), ("KOSDAQ", "101")),
) -> list:
    """Collect read-only market rankings and persist ranked observations."""
    all_inputs: list[MarketLeaderInput] = []
    for market, market_code in markets:
        trading_rows: list[MarketLeaderInput] = []
        rise_rows: list[MarketLeaderInput] = []
        trading_body = {"mrkt_tp": market_code, "mang_stk_incls": "1", "stex_tp": "3"}
        rise_body = {
            "mrkt_tp": market_code,
            "sort_tp": "1",
            "trde_qty_cnd": "0000",
            "stk_cnd": "0",
            "crd_cnd": "0",
            "updown_incls": "1",
            "pric_cnd": "0",
            "trde_prica_cnd": "0",
            "stex_tp": "3",
        }
        for page in client.post_pages("ka10032", "/api/dostk/rkinfo", trading_body):
            store.save_raw_page(run_id, f"__{market}__", page)
            trading_rows.extend(parse_trading_value_rows(page.payload, market=market))
        for page in client.post_pages("ka10027", "/api/dostk/rkinfo", rise_body):
            store.save_raw_page(run_id, f"__{market}__", page)
            rise_rows.extend(parse_rise_rate_rows(page.payload, market=market))
        all_inputs.extend(merge_leader_inputs(trading_rows, rise_rows))

    leaders = rank_market_leaders(all_inputs)
    store.save_leader_observations(run_id, as_of, leaders)
    return leaders
