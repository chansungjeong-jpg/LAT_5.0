# LAT 5.0

Paper-only trading research engine for the LAT multi-timeframe strategy.

## Current State

- Strategy contract / SSOT: `LAT_SIMPLE_v1_0_final_spec.md` (`SSOT_CORE.md` is a historical
  record only — do not use it as the current decision SSOT)
- Core Watchlist: `LAT_SIMPLE_v1.0_Watchlist.md`
- Live orders: disabled and not implemented
- LAT market DB: `data/lat5_market.db` (Kiwoom read APIs only)
- Default paper strategy: `hourly-pullback-reversal` v0.4.0
- Historical execution strength: unavailable, so current results are technical baselines

## Daily Pipeline

`scripts/run_daily_signal_reports.py` runs collect → data-health → the
monthly10/weekly5 recovery filter → the 60m trendline rank scan → a
location-filtered backtest → the desktop dashboard refresh, in that order,
failing closed at the first blocked step. Scheduled daily at 16:00 via
Windows Task Scheduler (`LAT5_Monthly10_Weekly5_Recovery`); logs land in
`reports/daily_pipeline/<date>.log`.

```powershell
$env:PYTHONPATH='src'
python scripts\run_daily_signal_reports.py --as-of 2026-08-20
```

- Top20 position dashboard: `dashboard/index.html` (desktop shortcut: `LAT 5.0 Top20 대시보드`)
- Monthly10/weekly5 filter output: `reports/monthly_weekly_filter/<date>.md`
- 60m trendline rank output: `reports/trendline_rank/<date>.md`
- Pattern-probability scanner (breakout+3d-entry, OOS t-test gated, monthly
  cadence, run manually): `scripts/pattern_probability_scan.py` →
  `reports/pattern_probability/<date>.md`

## Test

```powershell
pytest -q
```

## Backtest

```powershell
$env:PYTHONPATH='src'
python -m lat5.cli backtest `
  --source-db data\lat5_market.db `
  --watchlist LAT_SIMPLE_v1.0_Watchlist.md `
  --output-dir artifacts `
  --start 2026-03-03 `
  --end 2026-08-07 `
  --overwrite
```

The command writes a paper SQLite ledger, trades CSV, diagnostics JSON, and a
Markdown report. A zero-trade run is a valid blocked result and must not trigger
automatic threshold relaxation.

## Kiwoom Collection

The collector uses LAT-only credentials from `.env` and the dedicated
`data\kiwoom_token_cache.json`. It does not read or modify the `short` token
cache. An authentication failure blocks the complete run.

```powershell
$env:PYTHONPATH='src'
python -m lat5.cli collect `
  --db data\lat5_market.db `
  --watchlist LAT_SIMPLE_v1.0_Watchlist.md `
  --base-date 20260807 `
  --probe

python -m lat5.cli collect `
  --db data\lat5_market.db `
  --watchlist LAT_SIMPLE_v1.0_Watchlist.md `
  --base-date 20260807

python -m lat5.cli data-health `
  --db data\lat5_market.db `
  --watchlist LAT_SIMPLE_v1.0_Watchlist.md `
  --output-dir .
```
