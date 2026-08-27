from datetime import time

import numpy as np
import pandas as pd

INSTRUMENT = "EUR_USD"
PIP = 0.0001
EASTERN = "America/New_York"

"""
The foreign exchange day ends at 17:00 New York, so a bar is attributed to the
day it closes into rather than to its own calendar date. Everything downstream
depends on that: a prior day high read on calendar dates would cut Sunday
evening off the Monday session and silently change every pivot.
"""
DAY_ROLL_HOUR = 17

SIGNAL_CLOCK = time(7, 0)
FLAT_CLOCK = time(16, 0)

ASIAN_FROM_HOUR = 19
ASIAN_TO_HOUR = 3
LONDON_FROM_HOUR = 3

ATR_DAYS = 14
MOMENTUM_DAYS = (1, 5, 20)
TREND_DAYS = (20, 50)


def sessions(conn, instrument: str = INSTRUMENT) -> pd.DataFrame:
    """
    One row per foreign exchange day, from the one minute bars.

    Open and close are taken as the mid of the first and last bar of the day
    rather than from a daily feed, so the daily record and the intraday record
    can never disagree about the same session.
    """
    rows = conn.execute(
        """
        with marked as (
            select
                ((effective_time at time zone %s) - interval '17 hours')::date as fx_day,
                effective_time,
                (bid_open + ask_open) / 2 as mid_open,
                (bid_high + ask_high) / 2 as mid_high,
                (bid_low + ask_low) / 2 as mid_low,
                (bid_close + ask_close) / 2 as mid_close,
                (ask_close - bid_close) * 10000 as spread_pips
            from basis.price_bar
            where instrument_id = %s and granularity = 'M1'
        )
        select
            fx_day,
            min(effective_time) as opened_at,
            max(effective_time) as closed_at,
            (array_agg(mid_open order by effective_time))[1] as day_open,
            max(mid_high) as day_high,
            min(mid_low) as day_low,
            (array_agg(mid_close order by effective_time desc))[1] as day_close,
            percentile_cont(0.5) within group (order by spread_pips) as median_spread,
            count(*) as bars
        from marked
        group by fx_day
        order by fx_day
        """,
        (EASTERN, instrument),
    ).fetchall()

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    for column in ("day_open", "day_high", "day_low", "day_close", "median_spread"):
        frame[column] = frame[column].astype(float)
    return frame


def windows(conn, instrument: str = INSTRUMENT) -> pd.DataFrame:
    """
    The Asian range and the London move so far, both closed before the signal
    is published. A day trader's first two questions are where the overnight
    book settled and whether London has already picked a direction.
    """
    rows = conn.execute(
        """
        with marked as (
            select
                ((effective_time at time zone %s) - interval '17 hours')::date as fx_day,
                extract(hour from (effective_time at time zone %s)) as ny_hour,
                effective_time,
                (bid_high + ask_high) / 2 as mid_high,
                (bid_low + ask_low) / 2 as mid_low,
                (bid_close + ask_close) / 2 as mid_close
            from basis.price_bar
            where instrument_id = %s and granularity = 'M1'
        )
        select
            fx_day,
            max(mid_high) filter (where ny_hour >= %s or ny_hour < %s) as asian_high,
            min(mid_low) filter (where ny_hour >= %s or ny_hour < %s) as asian_low,
            (array_agg(mid_close order by effective_time)
               filter (where ny_hour >= %s and ny_hour < %s))[1] as london_open,
            (array_agg(mid_close order by effective_time desc)
               filter (where ny_hour >= %s and ny_hour < %s))[1] as pre_signal_close,
            max(mid_high) filter (where ny_hour >= %s and ny_hour < %s) as session_high,
            min(mid_low) filter (where ny_hour >= %s and ny_hour < %s) as session_low
        from marked
        group by fx_day
        order by fx_day
        """,
        (
            EASTERN, EASTERN, instrument,
            ASIAN_FROM_HOUR, ASIAN_TO_HOUR,
            ASIAN_FROM_HOUR, ASIAN_TO_HOUR,
            LONDON_FROM_HOUR, SIGNAL_CLOCK.hour,
            LONDON_FROM_HOUR, SIGNAL_CLOCK.hour,
            SIGNAL_CLOCK.hour, FLAT_CLOCK.hour,
            SIGNAL_CLOCK.hour, FLAT_CLOCK.hour,
        ),
    ).fetchall()

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    for column in (
        "asian_high", "asian_low", "london_open", "pre_signal_close",
        "session_high", "session_low",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["day_close"].shift(1)
    return pd.concat(
        [
            frame["day_high"] - frame["day_low"],
            (frame["day_high"] - previous_close).abs(),
            (frame["day_low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def features(daily: pd.DataFrame, intraday: pd.DataFrame) -> pd.DataFrame:
    """
    Every column is shifted so that a row carries only what had already closed
    when the signal is published at 07:00 New York.

    The prior day columns use shift(1) for that reason and not for smoothing.
    Reading today's high into today's features is the single easiest way to
    build a backtest that looks brilliant and cannot be traded.
    """
    frame = daily.merge(intraday, on="fx_day", how="left").sort_values("fx_day")
    frame = frame.reset_index(drop=True)

    frame["true_range"] = _true_range(frame)
    frame["atr"] = frame["true_range"].shift(1).rolling(ATR_DAYS).mean()
    frame["atr_pips"] = frame["atr"] / PIP

    """
    The trade lives inside the nine hours between publication and the flat
    hour, so its levels have to be scaled by what that window actually travels
    and not by what the whole day travels. Sized on the daily range instead,
    92 percent of sessions reach neither the target nor the invalidation and
    the definition stops describing a day trade at all.
    """
    frame["session_range"] = frame["session_high"] - frame["session_low"]
    frame["session_atr"] = frame["session_range"].shift(1).rolling(ATR_DAYS).mean()
    frame["session_atr_pips"] = frame["session_atr"] / PIP

    for column in ("day_open", "day_high", "day_low", "day_close"):
        frame[f"prior_{column.replace('day_', '')}"] = frame[column].shift(1)

    frame["prior_range_pips"] = (frame["prior_high"] - frame["prior_low"]) / PIP
    frame["prior_close_position"] = np.where(
        frame["prior_high"] > frame["prior_low"],
        (frame["prior_close"] - frame["prior_low"])
        / (frame["prior_high"] - frame["prior_low"]),
        0.5,
    )

    frame["pivot"] = (frame["prior_high"] + frame["prior_low"] + frame["prior_close"]) / 3
    frame["resistance_1"] = 2 * frame["pivot"] - frame["prior_low"]
    frame["support_1"] = 2 * frame["pivot"] - frame["prior_high"]

    frame["asian_range_pips"] = (frame["asian_high"] - frame["asian_low"]) / PIP
    frame["asian_position"] = np.where(
        frame["asian_high"] > frame["asian_low"],
        (frame["pre_signal_close"] - frame["asian_low"])
        / (frame["asian_high"] - frame["asian_low"]),
        0.5,
    )
    frame["london_move_pips"] = (
        frame["pre_signal_close"] - frame["london_open"]
    ) / PIP
    frame["gap_pips"] = (frame["london_open"] - frame["prior_close"]) / PIP
    frame["from_pivot_pips"] = (frame["pre_signal_close"] - frame["pivot"]) / PIP

    for days in MOMENTUM_DAYS:
        frame[f"momentum_{days}d_pips"] = (
            frame["day_close"].shift(1) - frame["day_close"].shift(1 + days)
        ) / PIP

    for days in TREND_DAYS:
        average = frame["day_close"].shift(1).rolling(days).mean()
        frame[f"from_average_{days}d_pips"] = (frame["pre_signal_close"] - average) / PIP

    frame["realised_vol_pips"] = (
        frame["true_range"].shift(1).rolling(ATR_DAYS).std() / PIP
    )
    frame["weekday"] = pd.to_datetime(frame["fx_day"]).dt.weekday

    return frame


FEATURE_COLUMNS = [
    "atr_pips",
    "session_atr_pips",
    "prior_range_pips",
    "prior_close_position",
    "asian_range_pips",
    "asian_position",
    "london_move_pips",
    "gap_pips",
    "from_pivot_pips",
    "momentum_1d_pips",
    "momentum_5d_pips",
    "momentum_20d_pips",
    "from_average_20d_pips",
    "from_average_50d_pips",
    "realised_vol_pips",
    "weekday",
]
