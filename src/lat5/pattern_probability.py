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
        row: dict[str, object] = {
            "breakout_date": event["date"],
            "entry_date": daily.index[entry_pos],
        }
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


def split_oos(
    events: pd.DataFrame, *, cutoff_frac: float = 0.7
) -> tuple[pd.DataFrame, pd.DataFrame]:
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
            n_train=n_train,
            n_test=n_test,
            t_train=None,
            t_test=None,
            win_rate_train=None,
            win_rate_test=None,
            avg_return_train=None,
            avg_return_test=None,
            sufficient_sample=False,
            passed=False,
        )
    t_train = t_stat(train_clean)
    t_test = t_stat(test_clean)
    passed = t_train >= t_threshold and t_test >= t_threshold
    return WindowStats(
        n_train=n_train,
        n_test=n_test,
        t_train=t_train,
        t_test=t_test,
        win_rate_train=float((train_clean > 0).mean()),
        win_rate_test=float((test_clean > 0).mean()),
        avg_return_train=float(train_clean.mean()),
        avg_return_test=float(test_clean.mean()),
        sufficient_sample=True,
        passed=passed,
    )


def evaluate_ticker(
    daily: pd.DataFrame, *, min_n: int = 30, t_threshold: float = 1.99
) -> TickerVerdict:
    events = find_breakout_events(daily)
    returns = compute_forward_returns(daily, events)
    train, test = split_oos(returns)
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
