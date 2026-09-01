from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from lat5.data import aggregate_weekly, drop_incomplete_trailing_session
from lat5.daily_ma_reaction import score_daily_reaction, wilder_rsi14
from lat5.hourly_abc_support import find_five_minute_reversal_entry, find_hourly_ma60_pullback, strong_hourly_breakout_at
from lat5.location_score import evaluate_daily_ma_reaction_gate
from lat5.patterns import breakout_rr_setup, confirmed_pivots
from lat5.scoring import daily_trend


_REQUIRED_ENTRY_CONTEXT_FIELDS = (
    "weekly_trend_ok",
    "m60_trend_ok",
    "m60_slope_pct",
    "daily_trend_ok",
)


def _is_unknown_required_context(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().upper() == "UNKNOWN"
    )


def _daily_sma5_distance_signal(daily: pd.DataFrame) -> tuple[float | None, str, int]:
    """Score whether completed daily closes are moving toward or away from SMA5."""
    if daily.empty or not {"close"}.issubset(daily.columns):
        return None, "UNKNOWN", 0
    close = pd.to_numeric(daily["close"], errors="coerce")
    sma5 = close.rolling(5, min_periods=5).mean()
    distance = ((close - sma5).abs() / sma5.abs()).replace([float("inf"), -float("inf")], pd.NA)
    distance = distance.dropna()
    if len(distance) < 3:
        return None, "UNKNOWN", 0

    recent = distance.iloc[-3:]
    current = float(recent.iloc[-1])
    delta = float(recent.iloc[-1] - recent.iloc[0])
    epsilon = 0.0001
    if delta < -epsilon:
        trend = "CLOSER"
        if current <= 0.01:
            score = 10
        elif current <= 0.02:
            score = 7
        elif current <= 0.03:
            score = 4
        else:
            score = 0
    elif delta > epsilon:
        trend = "WIDER"
        if current > 0.05:
            score = -10
        elif current > 0.03:
            score = -5
        else:
            score = 0
    else:
        trend = "STABLE"
        score = 0
    return current, trend, score


def _decline_rebound_slope_signal(daily: pd.DataFrame) -> tuple[float | None, str, int]:
    """Compare the daily-close decline slope from the last swing high down to
    its following swing low against the rebound slope from that low back up
    to today. A rebound steeper than the decline that preceded it scores as
    strength (mirrors a V-shaped recovery); a shallow rebound after a sharp
    drop does not.
    """
    if len(daily) < 10 or not {"high", "low", "close"}.issubset(daily.columns):
        return None, "UNKNOWN", 0
    pivots = confirmed_pivots(daily, left=2, right=2)
    if not pivots.highs or not pivots.lows:
        return None, "UNKNOWN", 0
    high_pos = pivots.highs[-1]
    low_candidates = [pos for pos in pivots.lows if pos > high_pos]
    if not low_candidates:
        return None, "UNKNOWN", 0
    low_pos = low_candidates[-1]
    current_pos = len(daily) - 1
    decline_days = low_pos - high_pos
    rebound_days = current_pos - low_pos
    if decline_days <= 0 or rebound_days <= 0:
        return None, "UNKNOWN", 0

    high_price = float(daily.iloc[high_pos]["high"])
    low_price = float(daily.iloc[low_pos]["low"])
    current_price = float(daily["close"].iloc[-1])
    if high_price <= 0 or low_price <= 0:
        return None, "UNKNOWN", 0

    decline_slope = (high_price - low_price) / high_price / decline_days
    if decline_slope <= 0:
        return None, "UNKNOWN", 0
    rebound_slope = (current_price - low_price) / low_price / rebound_days

    ratio = rebound_slope / decline_slope
    if ratio >= 2.0:
        return ratio, "STEEP_REBOUND", 10
    if ratio >= 1.0:
        return ratio, "REBOUND_STEEPER_THAN_DECLINE", 5
    return ratio, "REBOUND_SHALLOWER_THAN_DECLINE", 0


def daily_volume_ratio(daily: pd.DataFrame) -> float | None:
    """Latest completed daily volume vs. the mean of the prior 7 completed
    sessions (today excluded) -- the same smart-money-inflow ratio the
    position score's volume component is based on (final_spec 9.2). None
    when fewer than 8 sessions of history exist.
    """
    if "volume" not in daily.columns:
        return None
    daily = drop_incomplete_trailing_session(daily)
    if len(daily) < 8:
        return None
    volume = daily["volume"].astype(float)
    baseline_mean = float(volume.iloc[-8:-1].mean())
    if baseline_mean <= 0:
        return None
    return float(volume.iloc[-1]) / baseline_mean


def _daily_volume_score(ratio: float | None) -> int:
    """Score today's daily volume against the mean of the prior 7 completed
    daily bars (smart-money inflow proxy) rather than a single day-ago point.
    """
    if ratio is None:
        return 0
    if ratio < 0.8:
        return 0
    if ratio < 1.0:
        return 5
    if ratio < 1.2:
        return 10
    if ratio < 1.5:
        return 15
    if ratio < 2.0:
        return 20
    return 30


@dataclass(frozen=True)
class LocationScoreWeights:
    sector_flow: int = 15
    trend: int = 15
    volume: int = 25
    pullback_position: int = 20
    distance: int = 15
    rr_supply: int = 10


@dataclass(frozen=True)
class LocationScoreConfig:
    buy_ready: int = 80
    watch_high: int = 60
    watch: int = 40
    weights: LocationScoreWeights = field(default_factory=LocationScoreWeights)
    sector_min_score: int = 60
    sector_strong_score: int = 70
    sector_gate_enabled: bool = False
    daily_ema: int = 10
    m60_ema_fast: int = 20
    m60_ema_slow: int = 60
    recent_5_days_min_bullish: int = 3
    recent_10_days_min_bullish: int = 5
    strong_5_days_bullish: int = 4
    strong_10_days_bullish: int = 8
    weak_5_days_bullish: int = 2
    weak_10_days_bullish: int = 4
    anchor_volume_ratio: float = 1.5
    breakout_volume_ratio: float = 1.2
    pullback_volume_dry_ratio: float = 0.8
    m5_ema20_max_pct: float = 0.03
    m5_ema20_warning_pct: float = 0.05
    daily_ema10_max_pct: float = 0.10
    daily_ema10_warning_pct: float = 0.12
    min_rr: float = 1.5
    good_rr: float = 2.0
    supply_zone_lookback_days: int = 20


def build_context(
    *,
    daily: pd.DataFrame,
    daily_ema: pd.DataFrame,
    hourly: pd.DataFrame,
    minutes: pd.DataFrame,
    as_of: pd.Timestamp,
    cfg: LocationScoreConfig,
    breakout_lookback_bars: int = 40,
    cutoff: pd.Timestamp | None = None,
) -> dict:
    """Assemble a location_decision ctx dict from already-computed indicator frames.

    `as_of` is the historical day being decided FOR: `daily`/`daily_ema` rows at
    or after `as_of` are never read for trend/bull-count/RR inputs (only rows
    strictly before, per SSOT no-lookahead), matching the shifted-EMA
    convention already used by backtest.py's runners. `daily_ema` is expected
    to be `data.daily_ema_context(daily)` (or an empty frame with the same
    columns) so the row at exactly `as_of` reflects only prior closes.

    `hourly`/`minutes` (trend, breakout/pullback search, distance) default to
    the same pre-market boundary (`as_of` 09:00) as the daily fields. Pass an
    explicit `cutoff` to see bars completed later on `as_of`'s own calendar
    day — needed when gating a specific intraday candidate (e.g. a pullback
    that confirms mid-session the same day it broke out) rather than running
    a once-daily pre-market scan. Daily-bar fields always stay at the day
    boundary regardless of `cutoff`, since a daily bar isn't final until EOD.

    RR/overhead_supply_close use a documented proxy (trailing daily swing high
    as resistance) since Volume Profile is not implemented yet (see plan
    section 3-2) — recorded in `supply_zone_method` for backtest honesty.
    """
    ctx: dict = {"watchlist_ok": True, "sector_score": None}
    session_start = pd.Timestamp(as_of).normalize() + pd.Timedelta(hours=9)
    bar_cutoff = pd.Timestamp(cutoff) if cutoff is not None else session_start

    prior_daily = daily.loc[daily.index < as_of] if not daily.empty else daily
    price = float(prior_daily["close"].iloc[-1]) if not prior_daily.empty else None
    daily_reaction = score_daily_reaction(prior_daily, as_of)
    daily_reaction_details = {
        "reaction": daily_reaction.reaction,
        "base_score": daily_reaction.base_score,
        "quality_bonus": daily_reaction.quality_bonus,
        "score": daily_reaction.total_score,
        "status": daily_reaction.status,
        "reasons": list(daily_reaction.reasons),
        "unknown_fields": list(daily_reaction.unknown_fields),
        "quality_components": dict(daily_reaction.quality_components),
        "quality_reasons": list(daily_reaction.quality_reasons),
        "quality_method": daily_reaction.quality_method,
        "sma5": daily_reaction.sma5,
        "sma20": daily_reaction.sma20,
        "sma60": daily_reaction.sma60,
        "rsi14": daily_reaction.rsi14,
        "five_day_state": daily_reaction.five_day_state,
    }
    sma5_distance_pct, sma5_distance_trend, sma5_distance_score = _daily_sma5_distance_signal(
        prior_daily
    )
    slope_ratio, slope_state, slope_score = _decline_rebound_slope_signal(prior_daily)
    breakout_rr = breakout_rr_setup(prior_daily)
    ctx.update(
        {
            "daily_ma_reaction_score": daily_reaction.total_score,
            "daily_ma_reaction_state": daily_reaction.reaction,
            "daily_ma_reaction_reasons": list(daily_reaction.reasons),
            "daily_ma_reaction": daily_reaction_details,
            "sma5_distance_pct": sma5_distance_pct,
            "sma5_distance_trend": sma5_distance_trend,
            "sma5_distance_score": sma5_distance_score,
            "decline_rebound_slope_ratio": slope_ratio,
            "decline_rebound_slope_state": slope_state,
            "decline_rebound_slope_score": slope_score,
            "breakout_resistance_price": breakout_rr.resistance_price if breakout_rr else None,
            "breakout_entry_price": breakout_rr.entry_price if breakout_rr else None,
            "breakout_stop_price": breakout_rr.stop_price if breakout_rr else None,
            "breakout_target_price": breakout_rr.target_price if breakout_rr else None,
            "breakout_rr": breakout_rr.rr if breakout_rr else None,
        }
    )

    completed_weekly = aggregate_weekly(prior_daily)
    if not completed_weekly.empty:
        completed_weekly = completed_weekly.loc[completed_weekly.index < as_of]
        weekly_close = completed_weekly["close"].astype(float)
        weekly_ema10 = weekly_close.ewm(
            span=10, adjust=False, min_periods=10
        ).mean()
        weekly_ema20 = weekly_close.ewm(
            span=20, adjust=False, min_periods=20
        ).mean()
        if (
            not weekly_close.empty
            and not pd.isna(weekly_ema10.iloc[-1])
            and not pd.isna(weekly_ema20.iloc[-1])
        ):
            ctx["weekly_trend_ok"] = bool(
                weekly_close.iloc[-1] >= weekly_ema20.iloc[-1]
                and weekly_ema10.iloc[-1] >= weekly_ema20.iloc[-1]
            )

    if price is not None and as_of in daily_ema.index:
        ema_row = daily_ema.loc[as_of]
        if not (pd.isna(ema_row["ema10"]) or pd.isna(ema_row["ema20"])):
            state = daily_trend(price, float(ema_row["ema10"]), float(ema_row["ema20"]))
            ctx["daily_trend_ok"] = state in ("STRONG", "PULLBACK")
            ctx["daily_ema10_distance_pct"] = price / float(ema_row["ema10"]) - 1.0

    if len(prior_daily) >= 10:
        bull = prior_daily["close"].astype(float) > prior_daily["open"].astype(float)
        ctx["daily_bull_count_5"] = int(bull.iloc[-5:].sum())
        ctx["daily_bull_count_10"] = int(bull.iloc[-10:].sum())

    volume_ratio = daily_volume_ratio(prior_daily)
    if volume_ratio is not None:
        ctx["daily_volume_ratio"] = volume_ratio

    prior_hourly = (
        hourly.loc[hourly.index + pd.Timedelta(hours=1) <= bar_cutoff]
        if not hourly.empty
        else hourly
    )
    if len(prior_hourly) >= 1:
        last = prior_hourly.iloc[-1]
        if not (pd.isna(last["ema60"]) or pd.isna(last["ema120"])):
            ctx["m60_trend_ok"] = (
                float(last["close"]) >= float(last["ema60"]) >= float(last["ema120"])
            )
    ctx["m60_rsi14"] = (
        wilder_rsi14(prior_hourly["close"])
        if not prior_hourly.empty and "close" in prior_hourly.columns
        else None
    )
    if len(prior_hourly) >= 2:
        previous_ema60 = prior_hourly.iloc[-2].get("ema60")
        current_ema60 = prior_hourly.iloc[-1].get("ema60")
        if (
            previous_ema60 is not None
            and current_ema60 is not None
            and not pd.isna(previous_ema60)
            and not pd.isna(current_ema60)
            and float(previous_ema60) != 0
        ):
            ctx["m60_slope_pct"] = (
                float(current_ema60) - float(previous_ema60)
            ) / float(previous_ema60)

    breakout_pos = None
    search_start = max(0, len(prior_hourly) - breakout_lookback_bars)
    for pos in range(len(prior_hourly) - 1, search_start - 1, -1):
        if strong_hourly_breakout_at(prior_hourly, pos) is not None:
            breakout_pos = pos
            break

    if breakout_pos is None:
        ctx["pullback_state"] = "none"
    else:
        ctx["anchor_volume_ok"] = True
        ctx["bullish_candle_strength_ok"] = True
        pullback = find_hourly_ma60_pullback(prior_hourly, breakout_pos)
        if pullback is None:
            bars_since = len(prior_hourly) - 1 - breakout_pos
            ctx["pullback_state"] = "in_progress" if bars_since < 6 else "none"
        else:
            ctx["pullback_volume_dry"] = True
            ctx["pullback_state"] = "near_ema20"

            confirm_time = prior_hourly.index[pullback.pullback_pos] + pd.Timedelta(hours=1)
            trigger_minutes = minutes.loc[
                (minutes.index >= confirm_time) & (minutes.index < bar_cutoff)
            ]
            entry = find_five_minute_reversal_entry(
                trigger_minutes, start_time=confirm_time, pullback_low=pullback.pullback_low,
            )
            ctx["breakout_volume_ok"] = entry is not None

            if price is not None and price > pullback.pullback_low:
                lookback_start = as_of - pd.Timedelta(days=cfg.supply_zone_lookback_days)
                window = daily.loc[(daily.index < as_of) & (daily.index >= lookback_start)]
                if not window.empty:
                    resistance = float(window["high"].astype(float).max())
                    risk = price - pullback.pullback_low
                    if risk > 0:
                        ctx["price"] = price
                        ctx["support_price"] = pullback.pullback_low
                        ctx["resistance_price"] = resistance
                        ctx["rr"] = (resistance - price) / risk
                        ctx["overhead_supply_close"] = (resistance - price) / price < 0.02
                        ctx["supply_zone_method"] = "swing_high_proxy_v1"

    prior_minutes = minutes.loc[minutes.index < bar_cutoff] if not minutes.empty else minutes
    if not prior_minutes.empty:
        last_row = prior_minutes.iloc[-1]
        ema20_5m = last_row.get("ema20_5m")
        if ema20_5m is not None and not pd.isna(ema20_5m) and float(ema20_5m) != 0:
            ctx["m5_ema20_distance_pct"] = float(last_row["close"]) / float(ema20_5m) - 1.0

    return ctx


def evaluate_watchlist_position(ctx: dict, cfg: LocationScoreConfig) -> dict:
    """Score a Watchlist symbol's current entry position (0-100) with hard veto caps.

    Returns state in {BUY_READY, WATCH_HIGH, WATCH, IGNORE} plus reasons/wait_for
    for observability. See docs/superpowers/plans/
    LAT_SIMPLE_v1_Watchlist_Position_Finder_Refactoring.md section 14 for the
    veto rationale (v1 spec allowed a no-pullback chase, RR<1.5, and an
    overheated entry to all reach BUY_READY on score alone).
    """
    reasons: list[str] = []
    wait_for: list[str] = []
    vetoes: list[str] = []
    unknown_fields: list[str] = []

    def _get(key: str) -> object | None:
        value = ctx.get(key)
        if value is None:
            unknown_fields.append(key)
        return value

    if not ctx.get("watchlist_ok", False):
        return {
            "state": "IGNORE",
            "entry_eligible": False,
            "location_score": 0,
            "vetoes": ["NOT_ON_WATCHLIST"],
            "reasons": ["Watchlist 제외 종목"],
            "wait_for": [],
            "unknown_fields": [],
        }

    sector_score = _get("sector_score")
    if (
        cfg.sector_gate_enabled
        and sector_score is not None
        and sector_score < cfg.sector_min_score
    ):
        return {
            "state": "IGNORE",
            "entry_eligible": False,
            "location_score": 0,
            "vetoes": ["SECTOR_WEAK"],
            "reasons": ["섹터 돈흐름 약함"],
            "wait_for": ["Sector Score 60 이상 회복"],
            "unknown_fields": unknown_fields,
        }
    if sector_score is not None:
        if sector_score >= cfg.sector_strong_score:
            reasons.append("섹터 돈흐름 강함")
        elif sector_score >= cfg.sector_min_score:
            reasons.append("섹터 돈흐름 보통 이상")

    reaction_payload = ctx.get("daily_ma_reaction")
    reaction_unknown_fields = (
        tuple(
            str(field)
            for field in reaction_payload.get("unknown_fields", [])
            if str(field) != "rsi14"
        )
        if isinstance(reaction_payload, dict)
        else ()
    )
    daily_reaction_gate = evaluate_daily_ma_reaction_gate(
        ctx.get("daily_ma_reaction_score"),
        ctx.get("daily_ma_reaction_state"),
        reaction_unknown_fields,
    )
    unknown_fields.extend(daily_reaction_gate.unknown_fields)
    vetoes.extend(daily_reaction_gate.vetoes)

    required_context_unknown_fields = [
        field
        for field in _REQUIRED_ENTRY_CONTEXT_FIELDS
        if _is_unknown_required_context(ctx.get(field))
    ]
    if required_context_unknown_fields:
        unknown_fields.extend(required_context_unknown_fields)
        vetoes.append("ENTRY_PREREQUISITE_UNKNOWN")

    if ctx.get("daily_trend_ok") is True:
        reasons.append("일봉 추세 양호")
    else:
        wait_for.append("일봉 10EMA 회복")
    if ctx.get("m60_trend_ok") is True:
        reasons.append("60분 추세 회복")
    else:
        wait_for.append("60분 추세 회복")
    bull5 = ctx.get("daily_bull_count_5")
    bull10 = ctx.get("daily_bull_count_10")
    if bull5 is not None and bull10 is not None:
        if bull5 >= cfg.strong_5_days_bullish and bull10 >= cfg.strong_10_days_bullish:
            reasons.append("일봉 양봉 개수 우수")
        elif bull5 >= cfg.recent_5_days_min_bullish and bull10 >= cfg.recent_10_days_min_bullish:
            reasons.append("일봉 양봉 개수 기준 통과")
        elif bull5 >= cfg.weak_5_days_bullish or bull10 >= cfg.weak_10_days_bullish:
            reasons.append("일봉 양봉 개수 약함")
            wait_for.append("일봉 양봉 개수 회복")
        else:
            wait_for.append("일봉 양봉 개수 회복")
    else:
        wait_for.append("일봉 양봉 개수 회복")

    if ctx.get("anchor_volume_ok"):
        reasons.append("기준봉 거래량 증가")
    if ctx.get("pullback_volume_dry"):
        reasons.append("눌림 거래량 감소")
    if ctx.get("breakout_volume_ok"):
        reasons.append("돌파 거래량 증가")
    else:
        wait_for.append("돌파 거래량 증가 확인")
    if ctx.get("bullish_candle_strength_ok"):
        reasons.append("양봉 지속성 양호")

    pullback_state = _get("pullback_state")
    if pullback_state == "near_ema20":
        reasons.append("20EMA 부근 눌림 위치")
    elif pullback_state == "in_progress":
        reasons.append("눌림 진행 중")
        wait_for.append("20EMA 지지 확인")
    else:
        wait_for.append("눌림 위치 대기")
        vetoes.append("NO_PULLBACK")

    m5_dist = ctx.get("m5_ema20_distance_pct", 999)
    daily_dist = ctx.get("daily_ema10_distance_pct", 999)
    if m5_dist <= cfg.m5_ema20_max_pct and daily_dist <= cfg.daily_ema10_max_pct:
        reasons.append("이격도 정상")
    elif m5_dist <= cfg.m5_ema20_warning_pct and daily_dist <= cfg.daily_ema10_warning_pct:
        reasons.append("이격도 약간 부담")
        wait_for.append("이격도 축소")
    else:
        wait_for.append("과열 해소 대기")
        vetoes.append("OVERHEATED")

    rr = _get("rr") or 0
    overhead_supply_close = ctx.get("overhead_supply_close", True)
    if rr >= cfg.good_rr and not overhead_supply_close:
        reasons.append("손익비 우수")
    elif rr >= cfg.min_rr:
        reasons.append("손익비 최소 기준 통과")
    else:
        wait_for.append("손익비 1.5 이상 자리 대기")
        vetoes.append("RR_TOO_LOW")

    slope_pct = ctx.get("m60_slope_pct")
    if _is_unknown_required_context(slope_pct):
        slope_score = 0
    elif float(slope_pct) <= 0:
        slope_score = 0
    elif float(slope_pct) < 0.005:
        slope_score = 5
    else:
        slope_score = 10

    if bull5 is None:
        recent_bullish_score = 0
    elif bull5 >= cfg.strong_5_days_bullish:
        recent_bullish_score = 5
    elif bull5 >= cfg.weak_5_days_bullish:
        recent_bullish_score = 3
    else:
        recent_bullish_score = 0

    score_components = {
        "volume": _daily_volume_score(ctx.get("daily_volume_ratio")),
        "m60_location": 20 if ctx.get("m60_trend_ok") is True else 0,
        "daily_ma_reaction": daily_reaction_gate.component,
        "weekly_trend": 10 if ctx.get("weekly_trend_ok") is True else 0,
        "slope": slope_score,
        "recent_5d_bullish": recent_bullish_score,
        "daily_trend_persistence": 5 if ctx.get("daily_trend_ok") is True else 0,
        "daily_sma5_distance": int(ctx.get("sma5_distance_score", 0) or 0),
        "decline_rebound_slope": int(ctx.get("decline_rebound_slope_score", 0) or 0),
    }
    score = max(0, min(100, sum(score_components.values())))
    if daily_reaction_gate.component > 0:
        reasons.append("일봉 이평선 반응 점수 반영")
    if "DAILY_MA_WATCH_PRESSURE" in daily_reaction_gate.vetoes:
        wait_for.append("SMA5 종가 회복")
    if "DAILY_MA_REACTION_UNKNOWN" in daily_reaction_gate.vetoes:
        wait_for.append("일봉 이평선 필수 데이터 확인")
    if "DAILY_MA_HARD_BLOCK" in daily_reaction_gate.vetoes:
        wait_for.append("SMA20 종가 회복")

    if score >= cfg.buy_ready:
        state = "BUY_READY"
    elif score >= cfg.watch_high:
        state = "WATCH_HIGH"
    elif score >= cfg.watch:
        state = "WATCH"
    else:
        state = "IGNORE"

    if "RR_TOO_LOW" in vetoes:
        state = "IGNORE"
    elif any(
        veto in vetoes
        for veto in ("DAILY_MA_REACTION_UNKNOWN", "DAILY_MA_HARD_BLOCK")
    ):
        state = "IGNORE"
    elif "DAILY_MA_WATCH_PRESSURE" in vetoes and state in {
        "BUY_READY",
        "WATCH_HIGH",
    }:
        state = "WATCH"
    elif ("NO_PULLBACK" in vetoes or "OVERHEATED" in vetoes) and state == "BUY_READY":
        state = "WATCH"

    if "ENTRY_PREREQUISITE_UNKNOWN" in vetoes and state == "BUY_READY":
        state = "WATCH_HIGH"

    vetoes = list(dict.fromkeys(vetoes))
    unknown_fields = list(dict.fromkeys(unknown_fields))
    entry_eligible = state == "BUY_READY" and not vetoes

    current_price = ctx.get("price")
    stop_price = ctx.get("support_price")
    target_price = ctx.get("resistance_price")
    rr_breakdown = None
    if all(value is not None for value in (current_price, stop_price, target_price)):
        expected_loss = float(current_price) - float(stop_price)
        expected_reward = float(target_price) - float(current_price)
        if expected_loss > 0:
            rr_breakdown = {
                "current_price": float(current_price),
                "stop_price": float(stop_price),
                "target_price": float(target_price),
                "expected_loss": expected_loss,
                "expected_reward": expected_reward,
                "rr": expected_reward / expected_loss,
                "supply_zone_method": ctx.get("supply_zone_method"),
            }

    return {
        "state": state,
        "entry_eligible": entry_eligible,
        "location_score": score,
        "score_components": score_components,
        "vetoes": vetoes,
        "reasons": reasons,
        "wait_for": wait_for,
        "unknown_fields": unknown_fields,
        "rr": rr,
        "sector_score": sector_score,
        "m60_rsi14": ctx.get("m60_rsi14"),
        "rr_breakdown": rr_breakdown,
        "breakout_resistance_price": ctx.get("breakout_resistance_price"),
        "breakout_entry_price": ctx.get("breakout_entry_price"),
        "breakout_stop_price": ctx.get("breakout_stop_price"),
        "breakout_target_price": ctx.get("breakout_target_price"),
        "breakout_rr": ctx.get("breakout_rr"),
        "daily_ma_reaction": ctx.get(
            "daily_ma_reaction",
            {
                "score": ctx.get("daily_ma_reaction_score", 0),
                "reaction": ctx.get("daily_ma_reaction_state", "UNKNOWN"),
                "reasons": list(ctx.get("daily_ma_reaction_reasons", [])),
            },
        ),
    }
