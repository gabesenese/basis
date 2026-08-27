from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from basis.lanes import technical
from basis.study import daily

DAY = date(2026, 3, 10)


def bars(steps: list[tuple[float, float]], spread: float = 0.00015) -> pd.DataFrame:
    """
    steps are (high, low) mids for consecutive minutes. The first bar opens at
    the midpoint of its own range, which is what the entry is taken from.
    """
    rows = []
    start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    for index, (high, low) in enumerate(steps):
        mid_open = (high + low) / 2 if index else (high + low) / 2
        rows.append(
            {
                "fx_day": DAY,
                "effective_time": start + timedelta(minutes=index),
                "bid_open": mid_open - spread / 2,
                "bid_high": high - spread / 2,
                "bid_low": low - spread / 2,
                "bid_close": mid_open - spread / 2,
                "ask_open": mid_open + spread / 2,
                "ask_high": high + spread / 2,
                "ask_low": low + spread / 2,
                "ask_close": mid_open + spread / 2,
            }
        )
    return pd.DataFrame(rows)


def levels(atr: float = 0.0020) -> pd.DataFrame:
    return pd.DataFrame([{"fx_day": DAY, "atr": atr}])


def test_a_long_that_reaches_its_target_is_scored_at_the_target():
    frame = bars([(1.1000, 1.1000), (1.1016, 1.0999), (1.1000, 1.0999)])

    result = daily.outcomes(frame, levels(), stop_atr=0.5, target_atr=0.75)

    """
    The target sits 15 pips above the entry mid and is a level the bid has to
    reach, while the entry was paid at the ask, so the trade banks 14.25 pips
    and not 15. The missing 0.75 is half the spread, and it has to show up in
    the result rather than in a footnote.
    """
    assert result.loc[0, "long_end"] == "target"
    assert result.loc[0, "long_pips"] == pytest.approx(14.25, abs=0.01)


def test_a_long_that_reaches_its_invalidation_is_scored_at_the_stop():
    frame = bars([(1.1000, 1.1000), (1.1001, 1.0989), (1.1000, 1.0999)])

    result = daily.outcomes(frame, levels(), stop_atr=0.5, target_atr=0.75)

    assert result.loc[0, "long_end"] == "stop"
    assert result.loc[0, "long_pips"] < 0


def test_a_session_that_reaches_neither_is_flat_at_the_last_bar():
    frame = bars([(1.1000, 1.1000), (1.1004, 1.0997), (1.1002, 1.0999)])

    result = daily.outcomes(frame, levels(), stop_atr=0.5, target_atr=0.75)

    assert result.loc[0, "long_end"] == "flat"
    assert result.loc[0, "short_end"] == "flat"


def test_a_minute_holding_both_levels_is_resolved_as_the_loss():
    """
    A bar cannot say which of its own extremes came first. Resolving the
    ambiguity as the target would flatter the backtest precisely on the
    violent days, which are the days a day trader actually cares about.
    """
    frame = bars([(1.1000, 1.1000), (1.1020, 1.0980)])

    result = daily.outcomes(frame, levels(), stop_atr=0.5, target_atr=0.75)

    assert result.loc[0, "long_end"] == "stop"
    assert result.loc[0, "short_end"] == "stop"


def test_the_spread_is_charged_on_both_directions():
    frame = bars([(1.1000, 1.1000), (1.1000, 1.1000)])

    result = daily.outcomes(frame, levels(), stop_atr=0.5, target_atr=0.75)

    assert result.loc[0, "long_pips"] < 0
    assert result.loc[0, "short_pips"] < 0
    assert result.loc[0, "entry_spread_pips"] == pytest.approx(1.5, abs=0.01)


def test_a_session_without_a_dispersion_reading_is_skipped():
    frame = bars([(1.1000, 1.1000), (1.1010, 1.0990)])
    missing = pd.DataFrame([{"fx_day": DAY, "atr": float("nan")}])

    assert daily.outcomes(frame, missing).empty


def test_features_never_read_the_day_they_describe():
    """
    Rebuilds the feature frame after corrupting every value that closes after
    the signal is published. A feature that moves is a feature reading the
    future, and there is no cheaper way to catch one.
    """
    sessions = pd.DataFrame(
        {
            "fx_day": pd.date_range("2026-01-01", periods=80, freq="D").date,
            "day_open": np.linspace(1.10, 1.12, 80),
            "day_high": np.linspace(1.11, 1.13, 80),
            "day_low": np.linspace(1.09, 1.11, 80),
            "day_close": np.linspace(1.10, 1.12, 80),
        }
    )
    intraday = pd.DataFrame(
        {
            "fx_day": sessions["fx_day"],
            "asian_high": sessions["day_high"] - 0.001,
            "asian_low": sessions["day_low"] + 0.001,
            "london_open": sessions["day_open"],
            "pre_signal_close": sessions["day_open"] + 0.0005,
            "session_high": sessions["day_high"],
            "session_low": sessions["day_low"],
        }
    )

    honest = technical.features(sessions, intraday)

    tampered = sessions.copy()
    for column in ("day_high", "day_low", "day_close"):
        tampered.loc[tampered.index[-1], column] += 0.05
    poisoned = technical.features(tampered, intraday)

    columns = [c for c in technical.FEATURE_COLUMNS if c in honest.columns]
    last_honest = honest[columns].iloc[-1]
    last_poisoned = poisoned[columns].iloc[-1]

    pd.testing.assert_series_equal(last_honest, last_poisoned)


def test_the_session_dispersion_is_smaller_than_the_whole_day():
    sessions = pd.DataFrame(
        {
            "fx_day": pd.date_range("2026-01-01", periods=40, freq="D").date,
            "day_open": [1.10] * 40,
            "day_high": [1.11] * 40,
            "day_low": [1.09] * 40,
            "day_close": [1.10] * 40,
        }
    )
    intraday = pd.DataFrame(
        {
            "fx_day": sessions["fx_day"],
            "asian_high": [1.105] * 40,
            "asian_low": [1.095] * 40,
            "london_open": [1.10] * 40,
            "pre_signal_close": [1.10] * 40,
            "session_high": [1.1050] * 40,
            "session_low": [1.0950] * 40,
        }
    )

    frame = technical.features(sessions, intraday)
    last = frame.iloc[-1]

    assert last["session_atr_pips"] < last["atr_pips"]
