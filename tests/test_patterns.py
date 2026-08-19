import pandas as pd

import pytest

from lat5.patterns import (
    breakout_rr_setup,
    build_rising_channel,
    confirmed_pivots,
    find_abc,
    first_resistance_entry,
    is_anchor,
    nearest_support_below,
)


def _frame(high, low, close=None, open_=None, volume=None, amount=None):
    size = len(high)
    close = close or [(h + l) / 2 for h, l in zip(high, low)]
    open_ = open_ or close
    volume = volume or [100] * size
    amount = amount or [100.0] * size
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        },
        index=pd.date_range("2026-01-02 09:00", periods=size, freq="5min"),
    )


def test_confirmed_pivots_require_bars_on_both_sides():
    frame = _frame(
        high=[1, 2, 5, 2, 3, 6, 7],
        low=[0, 1, 2, 1, 0, 2, 3],
    )
    pivots = confirmed_pivots(frame, left=1, right=1)
    assert pivots.highs == (2,)
    assert pivots.lows == (4,)
    assert 6 not in pivots.highs


def test_build_rising_channel_connects_last_two_confirmed_highs_and_lows():
    frame = _frame(
        high=[105, 108, 110, 108, 106, 109, 112, 115, 112, 109, 111, 113, 114],
        low=[103, 105, 107, 104, 100, 106, 109, 112, 108, 104, 108, 110, 112],
    )
    frame.iloc[-1, frame.columns.get_loc("close")] = 113
    channel = build_rising_channel(frame)
    assert channel is not None
    assert channel.high_points == (2, 7)
    assert channel.low_points == (4, 9)
    assert round(channel.upper, 2) == 120.00
    assert round(channel.lower, 2) == 106.40
    assert 0.0 <= channel.position <= 0.5


def test_channel_rejects_falling_swing_pair():
    frame = _frame(
        high=[105, 108, 110, 108, 106, 109, 112, 109, 106, 104, 106, 108, 107],
        low=[103, 105, 107, 104, 100, 106, 109, 106, 102, 98, 102, 105, 104],
    )
    assert build_rising_channel(frame) is None


def _abc_frame(c_low=103.5):
    high = [101.0] * 20 + [103.0, 104.0, 106.0, 104.0, 105.0, 105.5, 104.5, 106.0, 106.5, 106.0]
    low = [99.0] * 20 + [99.5, 101.0, 103.0, 102.5, 103.5, 104.0, c_low, 104.0, 105.0, 104.5]
    close = [100.0] * 20 + [102.5, 103.0, 105.0, 103.0, 104.5, 105.0, 104.0, 105.5, 106.0, 105.0]
    open_ = [100.0] * 20 + [100.0, 102.5, 103.5, 105.0, 103.0, 104.5, 105.0, 104.0, 105.5, 106.0]
    amount = [100.0] * 20 + [250.0] + [100.0] * 9
    return _frame(high, low, close, open_, amount=amount)


def test_anchor_requires_amount_return_and_upper_close():
    frame = _abc_frame()
    assert is_anchor(frame, 20)
    frame.iloc[20, frame.columns.get_loc("amount")] = 199.9
    assert not is_anchor(frame, 20)


def test_find_abc_requires_higher_c_low_and_returns_entry_stop_expiry():
    setup = find_abc(_abc_frame(), anchor_pos=20, tick_size=0.5)
    assert setup is not None
    assert (setup.a_pos, setup.p_pos, setup.b_pos, setup.c_pos) == (22, 23, 25, 26)
    assert setup.entry == 106.0
    assert setup.stop == 103.0
    assert setup.expires_pos == 29


def test_find_abc_rejects_c_at_or_below_first_pullback():
    assert find_abc(_abc_frame(c_low=102.5), anchor_pos=20, tick_size=0.5) is None


def test_first_resistance_entry_picks_nearest_overhead_swing_high_not_the_highest():
    frame = _frame(
        high=[100, 102, 110, 102, 100, 103, 120, 103, 100, 101, 102, 103, 104],
        low=[98, 100, 108, 100, 98, 101, 118, 101, 98, 99, 100, 101, 102],
    )

    result = first_resistance_entry(frame)

    assert result is not None
    assert result.resistance_price == 110.0
    assert result.pivot_pos == 2
    assert result.entry_price == pytest.approx(110.0 * 1.002)


def test_first_resistance_entry_none_when_price_already_above_every_swing_high():
    frame = _frame(
        high=[100, 102, 110, 102, 100, 103, 120, 103, 100, 125, 126, 127, 128],
        low=[98, 100, 108, 100, 98, 101, 118, 101, 98, 123, 124, 125, 126],
    )

    assert first_resistance_entry(frame) is None


def test_first_resistance_entry_uses_custom_breakout_buffer():
    frame = _frame(
        high=[100, 102, 110, 102, 100, 103, 120, 103, 100, 101, 102, 103, 104],
        low=[98, 100, 108, 100, 98, 101, 118, 101, 98, 99, 100, 101, 102],
    )

    result = first_resistance_entry(frame, breakout_buffer_pct=0.01)

    assert result is not None
    assert result.entry_price == pytest.approx(110.0 * 1.01)


def _breakout_rr_frame():
    return _frame(
        high=[100, 102, 110, 102, 98, 103, 130, 103, 100, 101, 102, 103, 104, 103, 104],
        low=[98, 100, 108, 100, 96, 101, 128, 101, 98, 99, 100, 101, 102, 101, 102],
    )


def test_nearest_support_below_picks_closest_swing_low_under_current_price():
    frame = _breakout_rr_frame()

    support = nearest_support_below(frame)

    assert support == 98.0


def test_nearest_support_below_none_when_price_already_under_every_swing_low():
    frame = _frame(
        high=[130, 128, 120, 128, 130, 127, 110, 127, 130, 90, 89, 88, 87],
        low=[128, 126, 118, 126, 128, 125, 108, 125, 128, 88, 87, 86, 85],
    )

    assert nearest_support_below(frame) is None


def test_breakout_rr_setup_combines_entry_stop_and_next_resistance_target():
    frame = _breakout_rr_frame()

    setup = breakout_rr_setup(frame)

    assert setup is not None
    assert setup.resistance_price == 110.0
    assert setup.entry_price == pytest.approx(110.0 * 1.002)
    assert setup.stop_price == 98.0
    assert setup.target_price == 130.0
    expected_rr = (130.0 - setup.entry_price) / (setup.entry_price - 98.0)
    assert setup.rr == pytest.approx(expected_rr)


def test_breakout_rr_setup_none_when_no_further_resistance_beyond_entry():
    # Same R1 (110) and support (96) as _breakout_rr_frame, but truncated
    # before the second resistance peak ever forms -- entry and stop both
    # resolve fine, only the reward leg is missing.
    frame = _frame(
        high=[100, 102, 110, 102, 98, 103, 104],
        low=[98, 100, 108, 100, 96, 101, 102],
    )

    assert breakout_rr_setup(frame) is None
