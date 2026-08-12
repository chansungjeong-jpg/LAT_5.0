# LAT 5.0 Kiwoom Collector Design

## Goal

Collect every Core Watchlist symbol from Kiwoom REST into a LAT-owned database
without writing to `short`, issuing orders, or invalidating another project's
token. The collector must leave an auditable run record even when data is
missing or an API call fails.

## Scope

The first collector handles the 154 unique symbols parsed from
`LAT_SIMPLE_v1.0_Watchlist.md` and these read-only APIs:

| API | Data | Destination |
|---|---|---|
| `ka10081` | Daily OHLCV | `ohlcv_daily` |
| `ka10080` | Five-minute OHLCV | `ohlcv_minute` |
| `ka10046` | Intraday execution strength | `execution_strength` |
| `ka10059` | Foreign net buying | `investor_flow` |

No account, balance, pending-order, or order API is in scope. No scheduler or
automatic strategy promotion is in scope.

## Token Safety

The collector reads the token from
`C:\trading_system\short\kiwoom_token_cache.json` without modifying that file.
It never calls `/oauth2/token` and never refreshes a token.

- Missing cache or token: stop before the first API call with `TOKEN_MISSING`.
- Cache older than 12 hours: stop with `TOKEN_STALE`.
- Kiwoom `8005` or invalid-token response: stop the entire run with
  `TOKEN_INVALID`; do not retry and do not issue a new token.
- Logs may include token source and cache timestamp, never the token value.

This policy prevents LAT from starting a token-refresh loop against `short`.
A future dedicated LAT App Key may replace it, but that is outside this design.

## Architecture

```text
Watchlist parser
      |
      v
Read-only token provider -> rate-limited Kiwoom HTTP client
                                  |
                                  v
                       response parser + raw audit
                                  |
                                  v
                      data/lat5_market.db
                                  |
                                  v
                       data-health report
```

Modules remain separate:

- `token_provider.py`: validates and reads the shared cache.
- `kiwoom_client.py`: POST, continuation headers, rate limiting, and errors.
- `collector_store.py`: schema and idempotent SQLite writes.
- `collector.py`: API-specific requests, parsers, and run orchestration.
- `data_health.py`: coverage and freshness without changing data.
- `cli.py`: `collect` and `data-health` commands.

## Database Contract

All market tables include `provider='kiwoom'`, `collected_at`, and `run_id`.
Provider is part of every natural key so another provider cannot overwrite
Kiwoom rows.

```text
collection_runs
  run_id, started_at, finished_at, status, watchlist_count,
  success_count, error_count, token_cache_time

collection_errors
  run_id, ticker, api_id, error_code, message, occurred_at

raw_api_responses
  run_id, ticker, api_id, page_no, collected_at, payload_json

ohlcv_daily
  provider, ticker, date, open, high, low, close, volume, amount,
  collected_at, run_id
  PK(provider, ticker, date)

ohlcv_minute
  provider, ticker, datetime, interval, open, high, low, close, volume,
  amount, collected_at, run_id
  PK(provider, ticker, datetime, interval)

execution_strength
  provider, ticker, datetime, strength, collected_at, run_id
  PK(provider, ticker, datetime)

investor_flow
  provider, ticker, date, foreign_net_thousand, collected_at, run_id
  PK(provider, ticker, date)
```

Writes use transactions and `ON CONFLICT DO UPDATE` only inside the LAT DB.
Raw responses are append-only. Parsed rows are replaceable by the same provider
and natural key, preserving the latest `run_id` and collection timestamp.

## API And Pagination

Requests use `https://api.kiwoom.com`, Bearer authorization, and the official
`api-id` header. The client preserves `cont-yn` and `next-key` response headers
and follows continuation pages with a configurable maximum page count.

- Minimum delay between requests: 0.35 seconds.
- Network errors and HTTP 429/5xx: at most three attempts with bounded backoff.
- Kiwoom business errors: record once per ticker/API; do not convert to zero.
- Token errors: stop the run immediately.
- Every successful page is written to `raw_api_responses` before parsing.

`ka10046` is requested from `/api/dostk/mrkcond`. The expected response is
`cntr_str_tm[]`, with `cntr_tm` as the observation time and `cntr_str` as the
execution-strength value. The first live response is still treated as schema
discovery. Its raw keys
must be recorded and compared with the parser contract. If the expected time
and strength fields are absent, parsed strength remains empty and the run
records `SCHEMA_MISMATCH`; no candidate fallback field is guessed.

## Collection Flow

1. Parse and deduplicate Core Watchlist symbols.
2. Validate token cache without an API refresh.
3. Create a `RUNNING` row in `collection_runs`.
4. Probe one liquid symbol (`005930`) for all four APIs.
5. If token validation fails, end the run as `BLOCKED`. If only `ka10046`
   schema validation fails, disable parsed strength for the run, retain raw
   responses, and continue the other APIs as `PARTIAL`.
6. Collect all 154 symbols sequentially with continuation.
7. Commit each API response and parsed batch independently.
8. Mark the run `COMPLETE`, `PARTIAL`, or `BLOCKED`.
9. Generate a coverage/freshness report and keep strategy decisions disabled
   when required data remains unknown.

## Status Rules

- `COMPLETE`: all symbols attempted, no token/schema blocker, and no API error.
- `PARTIAL`: all symbols attempted but one or more symbol/API calls failed,
  returned no rows, or had a parser schema mismatch.
- `BLOCKED`: token unavailable/invalid, database failure, or Watchlist parsing
  failure.

Empty data and zero are distinct. Empty API data creates an error/audit record
and never inserts a zero-valued market row.

## Data Health

The report shows attempted and covered symbol counts separately for daily,
five-minute, execution strength, and foreign flow. It also reports minimum and
maximum timestamps, stale symbols, schema mismatches, and the latest run status.

Initial targets are diagnostic, not automatic threshold changes:

- Daily OHLCV coverage: at least 95 percent.
- Five-minute coverage: at least 90 percent.
- Foreign-flow coverage: at least 90 percent.
- Execution strength: probe schema verified and latest completed trading-day
  rows present.

Failure to meet a target blocks full-strategy validation but does not delete or
rewrite collected rows.

## Testing

- Unit tests use fake HTTP responses and temporary SQLite databases.
- Token tests prove cache reads are non-mutating and stale/8005 paths stop.
- Pagination tests prove headers propagate and page limits are enforced.
- Parser tests use captured, redacted fixtures; schema mismatch fails closed.
- Store tests prove provider-aware keys and idempotent upserts.
- Integration tests run one-symbol collection with a fake client.
- A live probe is a separate explicit command and performs no order/account API
  calls.

## Acceptance Criteria

1. Existing 29 tests remain green and new collector tests pass.
2. `short` DB and token cache hashes/modified times do not change during a run.
3. A probe run stores raw and parsed data only in `data/lat5_market.db`.
4. A full run attempts all 154 unique symbols and writes a data-health report.
5. Token or schema failure ends `BLOCKED` without fabricated values.
6. Backtest reads LAT data only after coverage gates are reported; its result is
   still labeled incomplete if execution strength or market/sector snapshots
   are unavailable historically.
