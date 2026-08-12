import pandas as pd

from lat5.patterns import build_rising_channel, confirmed_pivots, find_abc, is_anchor


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
