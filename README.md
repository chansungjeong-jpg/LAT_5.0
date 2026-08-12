# LAT 5.0

Paper-only trading research engine for the LAT multi-timeframe strategy.

## Current State

- Strategy contract / SSOT: `LAT_SIMPLE_v1_0_final_spec.md`
- Core Watchlist: `LAT_SIMPLE_v1.0_Watchlist.md`
- Live orders: disabled and not implemented
- LAT market DB: `data/lat5_market.db` (Kiwoom read APIs only)
- Default paper strategy: `hourly-pullback-reversal` v0.4.0
- Historical execution strength: unavailable, so current results are technical baselines

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
