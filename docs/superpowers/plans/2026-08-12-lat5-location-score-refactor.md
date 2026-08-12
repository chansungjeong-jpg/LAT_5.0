# LAT 5.0 Location Score Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the official ABC entry contract with a daily/weekly and 60-minute location-scoring engine whose highest-weight signal is volume, while keeping old ABC paths only as historical comparison code.

**Architecture:** The official path will read the Core Watchlist, evaluate completed weekly and daily context, score 60-minute EMA60/EMA120 location, normalized trend slope, and volume strength, then apply distance, supply-proxy, and RR hard gates. ABC modules remain callable only for legacy replay until a later removal decision.

**Tech Stack:** Python 3.13, pandas, SQLite read-only market adapter, pytest.

## Global Constraints

- Paper-only; no live order, broker order, notifier, or scheduler changes.
- Use only completed weekly, daily, and 60-minute bars; no look-ahead.
- Volume is the largest score component: 30/100 points.
- Official score weights: volume 30, 60-minute EMA location 25, weekly trend 15, daily trend 15, normalized slope 10, recent five-session bullish count 5.
- Distance, supply-zone proxy, and RR are hard gates; RR below 1.5 is REJECT.
- Supply-zone proxy must be labeled `swing_high_proxy_v1`; do not present it as Volume Profile.
- Missing required values remain UNKNOWN/WATCH or REJECT according to the SSOT; never fabricate values.
- ABC is excluded from the official decision path but existing legacy modules and historical tests are preserved in this pass.
- Core Watchlist is the initial universe and rolling snapshot; leader discovery, ranking, and replacement use full KOSPI/KOSDAQ market data.
- Leader Score weights are trading-value rank 60% and rise-rate rank 40%.
- Market Flow and Sector Flow are compass context; Leader Score performs stock discovery before location scoring.
- US Market Context uses delayed daily data through a replaceable `yfinance` adapter for research/backtest and post-close decisions only.
- Missing, stale, or incomplete US context is `UNKNOWN` and cannot produce a new `BUY`.
- US context is mapped through a versioned US-symbol -> Korean sector -> dynamically ranked domestic leader registry; mapping is auxiliary and never overrides domestic flow or location gates.

---

### Task 1: Update the SSOT contract

**Files:**
- Modify: `LAT_SIMPLE_v1_0_final_spec.md`
- Modify: `README.md`

**Interfaces:**
- Official pipeline: `Watchlist -> Weekly -> Daily -> 5-session bullish count -> 60m EMA location -> slope -> volume -> distance -> supply proxy -> RR -> BUY/WATCH/REJECT`.

- [ ] Replace ABC sections and output fields with the new location-score contract.
- [ ] Document the 100-point weights and the `swing_high_proxy_v1` limitation.
- [ ] State that ABC remains legacy-only and is not an official BUY condition.
- [ ] Verify no official pipeline or BUY condition still requires ABC.

### Task 2: Add failing tests for the pure location score

**Files:**
- Create: `tests/test_location_score.py`

**Interfaces:**
- `from lat5.location_score import LocationInputs, LocationScoreConfig, score_location`
- `score_location(inputs) -> LocationDecision`

- [ ] Test volume receives the highest weight and contributes at most 30 points.
- [ ] Test weekly/daily trend, five-session bullish count, 60-minute location, and slope contribute the documented maximums.
- [ ] Test distance overheat produces WATCH and does not become BUY from score alone.
- [ ] Test supply proxy missing or RR below 1.5 produces REJECT.
- [ ] Test missing required trend data fails closed.
- [ ] Run `pytest tests/test_location_score.py -q` and confirm the expected import/behavior failure before implementation.

### Task 3: Implement the pure location score

**Files:**
- Create: `src/lat5/location_score.py`

**Interfaces:**
- Frozen inputs and result dataclasses with explicit `unknown_fields`, `vetoes`, `reasons`, and `score`.
- Volume score is monotonic from 0 to 30.
- Official states are only `BUY`, `WATCH`, and `REJECT`.

- [ ] Implement the minimum dataclasses and deterministic component scoring.
- [ ] Implement normalized slope scoring without price-unit-dependent geometric angles.
- [ ] Implement hard-gate ordering: missing/failed market context, distance overheat, missing supply proxy, and RR failure.
- [ ] Run focused tests and confirm they pass.

### Task 4: Build weekly/daily/60-minute inputs from the read-only data adapter

**Files:**
- Modify: `src/lat5/data.py`
- Modify: `src/lat5/location_decision.py` or add a focused context adapter
- Test: `tests/test_location_score.py`

**Interfaces:**
- Completed weekly context derived from daily data.
- Five-session bullish count uses only completed daily bars before the decision timestamp.
- 60-minute EMA60/EMA120 position, slope, volume ratio, distance, and `swing_high_proxy_v1` are explicit fields.

- [ ] Add tests for weekly aggregation, five-session bullish count, and point-in-time cutoffs.
- [ ] Implement read-only context construction with no future-bar access.
- [ ] Preserve unknown fields instead of defaulting missing data to a passing value.
- [ ] Run focused context tests and the full test suite.

### Task 5: Connect the official Backtest path and retire ABC from default selection

**Files:**
- Modify: `src/lat5/backtest.py`
- Modify: `src/lat5/cli.py`
- Modify: `tests/test_cli.py`, `tests/test_backtest.py`

**Interfaces:**
- Default strategy uses the location score and official `BUY/WATCH/REJECT` decision.
- Legacy ABC choices remain explicitly labeled comparison-only in this pass.
- Every official decision stores the standard SSOT output fields and score diagnostics.

- [ ] Add a failing integration test proving the default runner invokes the location score and does not require ABC.
- [ ] Implement the smallest adapter from market data context to `score_location`.
- [ ] Keep legacy runners available without making them the default.
- [ ] Run focused integration tests, then `pytest -q`.

### Task 6: Final verification and evidence

**Files:**
- Modify: `reports/backtest_technical_baseline.md` if generated output format changes.

- [ ] Run `pytest -q`.
- [ ] Run `python -m compileall -q src`.
- [ ] Inspect the generated diagnostics for score components, unknown fields, vetoes, and proxy method.
- [ ] Report separately: tests, data-health, and strategy-validation status.
- [ ] Do not claim capital readiness without sufficient data coverage and resolved trade samples.
