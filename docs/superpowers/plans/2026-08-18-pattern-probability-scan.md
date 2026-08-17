# 패턴 확률 스캐너 v1 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 돌파+3거래일후진입 패턴을 종목별로 OOS 검증·유의성 판정해 `PASS`/`PARTIAL`/`FAIL`/`INSUFFICIENT_SAMPLE`로 분류하는 재사용 가능 도구를 만든다.

**Architecture:** DB 비의존 순수함수 모듈(`src/lat5/pattern_probability.py`) + Watchlist 순회 스크립트(`scripts/pattern_probability_scan.py`). 스펙: `docs/superpowers/specs/2026-08-18-pattern-probability-scan-design.md`.

**Tech Stack:** pandas만 사용(scipy 의존성 추가 안 함). 기존 `scripts/filter_monthly10_weekly5.py` CLI 인자 규약(`--db --watchlist --as-of`) 재사용.

---

### Task 1: 이벤트 탐지 + 순방향 수익률

**Files:**
- Create: `src/lat5/pattern_probability.py`
- Test: `tests/test_pattern_probability.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import pandas as pd
import pytest

from lat5.pattern_probability import find_breakout_events, compute_forward_returns


def _daily(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes, "volume": volumes}, index=index)


def test_find_breakout_events_requires_seven_percent_and_double_volume():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 10
    daily = _daily(closes, volumes)

    events = find_breakout_events(daily)

    assert list(events["pos"]) == [20]


def test_find_breakout_events_rejects_big_move_without_volume():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 31  # no 2x spike on the breakout day
    daily = _daily(closes, volumes)

    events = find_breakout_events(daily)

    assert events.empty


def test_compute_forward_returns_marks_missing_future_data_as_nan_not_dropped():
    # breakout at pos 20, entry at pos 23; only 4 bars remain after entry so
    # the 5-day exit (pos 28) is out of range but nothing else is.
    closes = [100.0] * 20 + [107.5] + [108.0] * 7
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 7
    daily = _daily(closes, volumes)
    events = find_breakout_events(daily)

    returns = compute_forward_returns(daily, events, entry_offset=3, hold_days=(5, 10))

    assert len(returns) == 1
    assert pd.isna(returns["ret_5"].iloc[0])
    assert pd.isna(returns["ret_10"].iloc[0])


def test_compute_forward_returns_computes_correct_ratio():
    closes = [100.0] * 20 + [110.0] + [110.0] * 2 + [121.0] + [110.0] * 4 + [132.0] + [110.0] * 20
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * (len(closes) - 21)
    daily = _daily(closes, volumes)
    events = find_breakout_events(daily)

    returns = compute_forward_returns(daily, events, entry_offset=3, hold_days=(5, 10))

    # entry = pos 23 (close 121.0), exit_5 = pos 28 (close 132.0)
    assert returns["ret_5"].iloc[0] == pytest.approx(132.0 / 121.0 - 1.0)
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `python -m pytest tests/test_pattern_probability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lat5.pattern_probability'`

- [ ] **Step 3: 최소 구현 작성**

```python
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def find_breakout_events(
    daily: pd.DataFrame,
    *,
    return_threshold: float = 0.07,
    volume_multiple: float = 2.0,
) -> pd.DataFrame:
    if len(daily) < 21:
        return pd.DataFrame({"date": [], "pos": []})
    close = daily["close"].astype(float)
    volume = daily["volume"].astype(float)
    ret = close.pct_change()
    vol20 = volume.rolling(20, min_periods=20).mean().shift(1)
    breakout = (ret >= return_threshold) & (volume >= volume_multiple * vol20)
    positions = [i for i, hit in enumerate(breakout.to_numpy()) if hit]
    return pd.DataFrame(
        {"date": [daily.index[i] for i in positions], "pos": positions}
    )


def compute_forward_returns(
    daily: pd.DataFrame,
    events: pd.DataFrame,
    *,
    entry_offset: int = 3,
    hold_days: tuple[int, ...] = (5, 10),
) -> pd.DataFrame:
    close = daily["close"].astype(float)
    rows = []
    for _, event in events.iterrows():
        breakout_pos = int(event["pos"])
        entry_pos = breakout_pos + entry_offset
        if entry_pos >= len(daily):
            continue
        row = {"breakout_date": event["date"], "entry_date": daily.index[entry_pos]}
        entry_price = close.iloc[entry_pos]
        for hold in hold_days:
            exit_pos = entry_pos + hold
            if exit_pos >= len(daily):
                row[f"ret_{hold}"] = float("nan")
            else:
                row[f"ret_{hold}"] = close.iloc[exit_pos] / entry_price - 1.0
        rows.append(row)
    columns = ["breakout_date", "entry_date"] + [f"ret_{hold}" for hold in hold_days]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `python -m pytest tests/test_pattern_probability.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/lat5/pattern_probability.py tests/test_pattern_probability.py
git commit -m "feat: detect breakout events and compute forward returns"
```

---

### Task 2: OOS 분할 + t검정 + 종목 판정

**Files:**
- Modify: `src/lat5/pattern_probability.py`
- Test: `tests/test_pattern_probability.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from lat5.pattern_probability import evaluate_ticker, split_oos, t_stat


def test_split_oos_divides_by_event_count_not_calendar_time():
    events = pd.DataFrame({"breakout_date": pd.date_range("2020-01-01", periods=10, freq="D")})
    train, test = split_oos(events, cutoff_frac=0.7)
    assert len(train) == 7
    assert len(test) == 3
    assert train["breakout_date"].max() < test["breakout_date"].min()


def test_t_stat_of_all_zero_returns_is_zero():
    assert t_stat(pd.Series([0.0, 0.0, 0.0])) == 0.0


def test_t_stat_matches_hand_computed_value():
    returns = pd.Series([0.02, 0.04, 0.06, 0.08, 0.10])
    # mean=0.06, sample std=0.031623, se=0.031623/sqrt(5)=0.014142
    # t = 0.06 / 0.014142 = 4.2426
    assert t_stat(returns) == pytest.approx(4.2426, abs=0.001)


def test_evaluate_ticker_insufficient_sample_below_min_n():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 10
    daily = _daily(closes, volumes)

    verdict = evaluate_ticker(daily, min_n=30, t_threshold=1.99)

    assert verdict.verdict == "INSUFFICIENT_SAMPLE"


def test_evaluate_ticker_pass_requires_both_windows_significant_in_both_splits():
    import numpy as np

    rng = np.random.default_rng(seed=7)
    n_days = 400
    closes = [100.0]
    volumes = []
    for _ in range(n_days):
        volumes.append(1000.0)
        closes.append(closes[-1] * (1.0 + rng.normal(0.0005, 0.01)))
    closes = closes[1:]
    # force 60 clean breakout events with a strong positive forward drift
    for k in range(60):
        i = 25 + k * 6
        if i + 15 >= len(closes):
            break
        closes[i] = closes[i - 1] * 1.09
        volumes[i] = 3000.0
        for j in range(1, 14):
            closes[i + j] = closes[i + j - 1] * 1.01
    daily = _daily(closes, volumes)

    verdict = evaluate_ticker(daily, min_n=15, t_threshold=1.5)

    assert verdict.verdict in ("PASS", "PARTIAL")
    assert verdict.hold_5.n_train >= 15
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `python -m pytest tests/test_pattern_probability.py -v`
Expected: FAIL — `split_oos`/`t_stat`/`evaluate_ticker` not defined

- [ ] **Step 3: 구현 추가** (파일 하단에 이어 붙임)

```python
def split_oos(events: pd.DataFrame, *, cutoff_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = events.sort_values("breakout_date").reset_index(drop=True)
    cutoff = int(len(ordered) * cutoff_frac)
    return ordered.iloc[:cutoff], ordered.iloc[cutoff:]


def t_stat(returns: pd.Series) -> float:
    clean = returns.dropna()
    n = len(clean)
    if n < 2:
        return 0.0
    std = clean.std(ddof=1)
    if std == 0:
        return 0.0
    return float(clean.mean() / (std / (n ** 0.5)))


@dataclass(frozen=True)
class WindowStats:
    n_train: int
    n_test: int
    t_train: float | None
    t_test: float | None
    win_rate_train: float | None
    win_rate_test: float | None
    avg_return_train: float | None
    avg_return_test: float | None
    sufficient_sample: bool
    passed: bool


@dataclass(frozen=True)
class TickerVerdict:
    verdict: str
    hold_5: WindowStats
    hold_10: WindowStats


def _window_stats(
    train_col: pd.Series, test_col: pd.Series, *, min_n: int, t_threshold: float
) -> WindowStats:
    train_clean = train_col.dropna()
    test_clean = test_col.dropna()
    n_train, n_test = len(train_clean), len(test_clean)
    sufficient = n_train >= min_n and n_test >= min_n
    if not sufficient:
        return WindowStats(
            n_train=n_train, n_test=n_test, t_train=None, t_test=None,
            win_rate_train=None, win_rate_test=None,
            avg_return_train=None, avg_return_test=None,
            sufficient_sample=False, passed=False,
        )
    t_train = t_stat(train_clean)
    t_test = t_stat(test_clean)
    passed = t_train >= t_threshold and t_test >= t_threshold
    return WindowStats(
        n_train=n_train, n_test=n_test, t_train=t_train, t_test=t_test,
        win_rate_train=float((train_clean > 0).mean()),
        win_rate_test=float((test_clean > 0).mean()),
        avg_return_train=float(train_clean.mean()),
        avg_return_test=float(test_clean.mean()),
        sufficient_sample=True, passed=passed,
    )


def evaluate_ticker(
    daily: pd.DataFrame, *, min_n: int = 30, t_threshold: float = 1.99
) -> TickerVerdict:
    events = find_breakout_events(daily)
    returns = compute_forward_returns(daily, events)
    train, test = split_oos(returns.rename(columns={"breakout_date": "breakout_date"}))
    hold_5 = _window_stats(train["ret_5"], test["ret_5"], min_n=min_n, t_threshold=t_threshold)
    hold_10 = _window_stats(train["ret_10"], test["ret_10"], min_n=min_n, t_threshold=t_threshold)

    if not hold_5.sufficient_sample or not hold_10.sufficient_sample:
        verdict = "INSUFFICIENT_SAMPLE"
    elif hold_5.passed and hold_10.passed:
        verdict = "PASS"
    elif hold_5.passed or hold_10.passed:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    return TickerVerdict(verdict=verdict, hold_5=hold_5, hold_10=hold_10)
```

Also add `from dataclasses import dataclass` to the existing `from dataclasses import dataclass` import line at the top of the file (already present from Task 1 if you used it; otherwise add it).

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `python -m pytest tests/test_pattern_probability.py -v`
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/lat5/pattern_probability.py tests/test_pattern_probability.py
git commit -m "feat: add OOS split, significance test, and ticker verdict"
```

---

### Task 3: Watchlist 스캔 스크립트

**Files:**
- Create: `scripts/pattern_probability_scan.py`

- [ ] **Step 1: 스크립트 작성**

```python
from __future__ import annotations

import argparse
from pathlib import Path

from lat5.data import KiwoomDataStore, parse_watchlist
from lat5.pattern_probability import evaluate_ticker


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def build_report(rows: list[tuple[str, str, object]]) -> str:
    lines = [
        "| 코드 | 종목 | 판정 | n_train(5d) | n_test(5d) | t_train(5d) | t_test(5d) | "
        "n_train(10d) | n_test(10d) | t_train(10d) | t_test(10d) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ticker, name, verdict in rows:
        h5, h10 = verdict.hold_5, verdict.hold_10
        lines.append(
            f"| {ticker} | {name} | {verdict.verdict} | {h5.n_train} | {h5.n_test} | "
            f"{_fmt(h5.t_train)} | {_fmt(h5.t_test)} | {h10.n_train} | {h10.n_test} | "
            f"{_fmt(h10.t_train)} | {_fmt(h10.t_test)} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    items = parse_watchlist(args.watchlist)
    rows = []
    with KiwoomDataStore(args.db) as store:
        for item in items:
            daily = store.load_daily(item.ticker)
            if daily.empty:
                continue
            verdict = evaluate_ticker(daily.sort_index())
            rows.append((item.ticker, item.name, verdict))

    out_dir = Path("reports") / "pattern_probability"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.as_of}.md"
    out_path.write_text(
        f"# 패턴 확률 스캔 — {args.as_of}\n\n" + build_report(rows) + "\n",
        encoding="utf-8",
    )
    print(f"output={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실제 DB로 수동 실행 확인**

Run:
```
PYTHONPATH=src python scripts/pattern_probability_scan.py --db data/lat5_market.db --watchlist LAT_SIMPLE_v1.0_Watchlist.md --as-of 2026-08-17
```
Expected: `output=reports/pattern_probability/2026-08-17.md` 생성, 파일 열어보면 154행 이내 표

- [ ] **Step 3: compileall + 전체 테스트**

Run: `python -m compileall -q src scripts tests && python -m pytest -q`
Expected: `COMPILE_OK` 상당, 전체 통과(9개 신규 포함)

- [ ] **Step 4: 커밋**

```bash
git add scripts/pattern_probability_scan.py reports/pattern_probability/
git commit -m "feat: add pattern probability scan script"
```

---

## Self-Review 결과 (계획 작성자 자체 점검)

- 스펙 4.1(이벤트/수익률/분할/t검정/판정)·4.2(판정로직)·4.3(스크립트)·4.4(테스트) 전부 Task 1-3에 대응. 4.4의 fixture 기반 무의존 테스트 요건 충족(DB 미사용).
- 스펙 6장(v1 제외 항목)은 코드에 아무 것도 추가하지 않음으로써 자연히 충족(거래비용 계산 없음, watchlist 과거 재구성 없음, Bonferroni 없음).
- 스펙 7장 에러처리: `find_breakout_events`가 20행 미만 시 빈 프레임 반환 → `evaluate_ticker`가 자동으로 `INSUFFICIENT_SAMPLE` 처리(Task 1 Step 3 `len(daily) < 21` 체크).
