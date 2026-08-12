# LAT 5.0 Core SSOT

## Scope

- Trade only symbols listed in `LAT_SIMPLE_v1.0_Watchlist.md` Core Watchlist.
- Exclude display and game/content sectors.
- Use Kiwoom REST data. Missing required values are `UNKNOWN`; never invent values.
- The first release is paper-only. No live order path is permitted.

## Decision Pipeline

### Active Paper Strategy: `hourly-pullback-reversal` (v0.4.0)

The active entry strategy uses a strong 60-minute breakout followed by a
time-bounded MA60 pullback and a five-minute reversal. It replaces the
over-selective 60-minute ABC/C-high entry as the default paper strategy.

```text
Core Watchlist -> strong completed 60m MA60 or MA120 breakout
               -> 2nd through 6th completed 60m bar supports EMA60 +/-1%
               -> pullback volume is below breakout-bar volume
               -> bullish 5m close breaks prior-three-bar high with 1.5x volume
               -> next 5m open entry no later than 14:30
```

- MA60 and MA120 are exponential moving averages of completed 60-minute bars.
- Strong breakout requires a 0.5 percent close distance, bullish body at least
  0.8 ATR20, close in the upper 25 percent, and 2.0 times prior-20 mean volume.
- Pullback low must be within 1.0 percent of EMA60 and the completed 60-minute
  close must remain above EMA60.
- The five-minute trigger requires a bullish close above the prior three
  completed bars' high and at least 1.5 times prior-20 mean volume.
- Initial stop is one Kiwoom-valid tick below the pullback low.
- Sell half at 1R and move the remaining stop to entry. Exit the remainder at
  2R, on a completed five-minute close below EMA20, or at session close.
- If price does not reach 0.5R within 60 minutes, exit at that bar's close.
- Do not open a new position after 14:30.
- At most one filled trade per symbol per session.
- The legacy `abc`, `hourly-ma-or`, and `hourly-abc-support` strategies remain
  callable only for comparison and replay.

The original LAT pipeline below is retained as the broader scoring design; it
is not the default paper entry strategy.

```text
Market -> Sector -> Core Watchlist -> Daily Trend -> 60m Trend/Channel
       -> 5m Anchor/ABC -> Distance -> RR -> BUY/WATCH/REJECT
```

## Market Gate

An index is trend-OK when price is at or above daily EMA20 and EMA10 is at or
above EMA20.

- Both KOSPI and KOSDAQ trend-OK: `BUY` regime.
- Exactly one trend-OK: `SELECTIVE_BUY` regime.
- Neither trend-OK: `RISK_OFF`; block new entries.

## Sector Score

Total score is 100: price trend 30, same-time turnover 30, execution strength
25, and foreign flow 15. A sector requires at least three valid members and at
least 70 percent Core Watchlist coverage.

- `score >= 70`: BUY candidate.
- `55 <= score < 70`: WATCH.
- `score < 55`: REJECT.
- Missing fields use score bounds. If the confirmed score is already at least
  70, it can pass. If confirmed score plus all missing weights is below 70, it
  fails. Otherwise the result is `DATA_UNKNOWN/WATCH`.

Per-symbol price trend points:

- Price >= EMA10 and EMA10 >= EMA20: 30.
- EMA20 <= price < EMA10 and EMA10 >= EMA20: 15.
- Otherwise: 0.

Turnover compares current cumulative amount with the last 20 sessions at the
same time: `<0.8=0`, `0.8=5`, `1.0=10`, `1.2=15`, `1.5=20`, `2.0=30`.

Execution strength uses Kiwoom `ka10046`: `<90=0`, `90=5`, `100=10`,
`110=15`, `120=20`, `140=25`.

Foreign flow uses Kiwoom `ka10059` after 09:10. It is current-day cumulative
foreign net buy amount divided by current-day turnover: `<=0=0`, `0=3`,
`0.5=6`, `1.0=9`, `2.0=12`, `3.0=15` percent breakpoints.

## Daily And 60-Minute Context

Symbol daily trend is valid when price >= EMA20 and EMA10 >= EMA20. Price at or
above EMA10 is strong; price between EMA20 and EMA10 is a pullback candidate.

60-minute trend requires price >= EMA60 and EMA60 >= EMA120. Build channels
from the last 40 completed 60-minute bars. A pivot has two completed bars on
each side. A valid rising channel has at least two confirmed swing highs and
two confirmed swing lows, both pairs rising, with projected upper > lower.

Channel position is `(price - lower) / (upper - lower)`:

- Below 0: REJECT.
- 0 through 0.50: priority candidate.
- Above 0.50 and below 0.90: allowed subject to RR.
- 0.90 or above: WATCH; no new entry.
- Invalid channel: `CHANNEL_UNKNOWN/WATCH`.

## Five-Minute Trigger

Anchor candle:

- Amount >= 2.0 times the previous 20 completed five-minute bars' average.
- Candle return >= 1.5 percent.
- Close is within the upper 40 percent of the candle range.

Search at most 36 five-minute bars after Anchor. Five-minute pivots use one
completed bar on each side.

```text
A = first confirmed swing high after Anchor
P = first confirmed swing low after A
B = first confirmed swing high after P
C = first confirmed swing low after B
```

Valid ABC requires A above Anchor high, P at or above Anchor low, P retracement
no greater than 60 percent, B recovery at least 50 percent, and C > P.

- Entry trigger: B high plus one Kiwoom-valid tick.
- Initial stop: C low minus one Kiwoom-valid tick.
- Entry limit: trigger plus two ticks; never chase above it.
- Entry expires after three completed five-minute bars.
- Recalculate risk and RR from actual fill.

## Risk And Exit

- Initial paper capital: KRW 100,000,000.
- Risk per trade: 0.5 percent; selective regime: 0.25 percent.
- Maximum symbol exposure: 20 percent.
- Maximum concurrent positions: 3; selective regime: 1.
- Maximum sector exposure: 30 percent.
- Daily loss gate: stop new entries at -2 percent.
- Initial stop may never move down. Stop registration failure forces exit.
- Target is the nearer of the nearest resistance and 2R. Minimum RR is 1.5;
  selective regime requires 2.0.

Paper exits are evaluated as three independent strategy versions: fixed full
exit, break-even plus five-minute trailing, and partial exit plus 60-minute
channel trailing. Every decision and result is stored with `strategy_id` and
`algorithm_version`; promotion remains manual.

## Backtest Honesty

- Signals use only information completed at the decision timestamp.
- BUY, WATCH, and REJECT decisions are all persisted.
- Fees, tax, slippage, gaps, and next-available prices are recorded.
- Historical execution-strength data is currently absent. A run missing it is
  a labeled technical baseline, not a full-strategy validation.
