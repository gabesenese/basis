import numpy as np
import pandas as pd

from basis.lanes import technical

PIP = technical.PIP
STOP_ATR = 1.0
TARGET_ATR = 1.5

"""
When a single minute contains both the invalidation and the target, a bar
cannot say which came first, so the trade is resolved as the loss. Any other
convention flatters the backtest exactly on the volatile days where the
difference matters most.
"""
AMBIGUOUS_MINUTE_RESOLVES_TO = "stop"


def session_bars(conn, instrument: str = technical.INSTRUMENT) -> pd.DataFrame:
    rows = conn.execute(
        """
        select
            ((effective_time at time zone %s) - interval '17 hours')::date as fx_day,
            effective_time,
            bid_open, bid_high, bid_low, bid_close,
            ask_open, ask_high, ask_low, ask_close
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
          and extract(hour from (effective_time at time zone %s)) >= %s
          and extract(hour from (effective_time at time zone %s)) < %s
        order by effective_time
        """,
        (
            technical.EASTERN,
            instrument,
            technical.EASTERN,
            technical.SIGNAL_CLOCK.hour,
            technical.EASTERN,
            technical.FLAT_CLOCK.hour,
        ),
    ).fetchall()

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    for column in frame.columns:
        if column not in ("fx_day", "effective_time"):
            frame[column] = frame[column].astype(float)
    return frame


def _resolve(highs, lows, target: float, stop: float, upward: bool):
    """
    Returns the index of the bar that ended the trade and which level it hit,
    or None when neither was reached before the flat hour.
    """
    if upward:
        hit_target = highs >= target
        hit_stop = lows <= stop
    else:
        hit_target = lows <= target
        hit_stop = highs >= stop

    first_target = int(np.argmax(hit_target)) if hit_target.any() else None
    first_stop = int(np.argmax(hit_stop)) if hit_stop.any() else None

    if first_target is None and first_stop is None:
        return None, "flat"
    if first_stop is None:
        return first_target, "target"
    if first_target is None:
        return first_stop, "stop"
    if first_target < first_stop:
        return first_target, "target"
    return first_stop, "stop"


def outcomes(
    bars: pd.DataFrame,
    levels: pd.DataFrame,
    stop_atr: float = STOP_ATR,
    target_atr: float = TARGET_ATR,
) -> pd.DataFrame:
    """
    Both directions are resolved for every session, because a model has to
    learn which side was right and can only do that if the day carries the
    answer for both.
    """
    grouped = {day: chunk for day, chunk in bars.groupby("fx_day", sort=False)}
    records = []

    for row in levels.itertuples():
        chunk = grouped.get(row.fx_day)
        if chunk is None or len(chunk) < 2 or not np.isfinite(row.atr):
            continue

        entry_ask = float(chunk["ask_open"].iloc[0])
        entry_bid = float(chunk["bid_open"].iloc[0])
        mid = (entry_ask + entry_bid) / 2

        bid_high = chunk["bid_high"].to_numpy()
        bid_low = chunk["bid_low"].to_numpy()
        ask_high = chunk["ask_high"].to_numpy()
        ask_low = chunk["ask_low"].to_numpy()

        long_target = mid + target_atr * row.atr
        long_stop = mid - stop_atr * row.atr
        short_target = mid - target_atr * row.atr
        short_stop = mid + stop_atr * row.atr

        long_index, long_end = _resolve(bid_high, bid_low, long_target, long_stop, True)
        short_index, short_end = _resolve(
            ask_high, ask_low, short_target, short_stop, False
        )

        long_exit = {
            "target": long_target,
            "stop": long_stop,
            "flat": float(chunk["bid_close"].iloc[-1]),
        }[long_end]
        short_exit = {
            "target": short_target,
            "stop": short_stop,
            "flat": float(chunk["ask_close"].iloc[-1]),
        }[short_end]

        records.append(
            {
                "fx_day": row.fx_day,
                "entry_mid": mid,
                "entry_ask": entry_ask,
                "entry_bid": entry_bid,
                "entry_spread_pips": (entry_ask - entry_bid) / PIP,
                "long_end": long_end,
                "short_end": short_end,
                "long_pips": (long_exit - entry_ask) / PIP,
                "short_pips": (entry_bid - short_exit) / PIP,
                "long_minutes": None if long_index is None else long_index + 1,
                "short_minutes": None if short_index is None else short_index + 1,
                "session_move_pips": (
                    float(chunk["bid_close"].iloc[-1]) - entry_ask
                ) / PIP,
            }
        )

    return pd.DataFrame(records)


def build(
    conn,
    instrument: str = technical.INSTRUMENT,
    stop_atr: float = STOP_ATR,
    target_atr: float = TARGET_ATR,
    bars: pd.DataFrame | None = None,
) -> pd.DataFrame:
    daily = technical.sessions(conn, instrument)
    if daily.empty:
        return pd.DataFrame()

    frame = technical.features(daily, technical.windows(conn, instrument))
    levels = frame[["fx_day", "session_atr"]].dropna().rename(
        columns={"session_atr": "atr"}
    )

    if bars is None:
        bars = session_bars(conn, instrument)

    resolved = outcomes(bars, levels, stop_atr, target_atr)
    if resolved.empty:
        return pd.DataFrame()

    joined = frame.merge(resolved, on="fx_day", how="inner")
    joined["better_side"] = np.where(
        joined["long_pips"] > joined["short_pips"], "long", "short"
    )
    joined["long_won"] = (joined["long_end"] == "target").astype(int)
    joined["short_won"] = (joined["short_end"] == "target").astype(int)
    return joined.sort_values("fx_day").reset_index(drop=True)


def base_rates(frame: pd.DataFrame) -> dict:
    """
    What a coin earns on this trade definition, before any model exists. Every
    later claim of skill is a claim against these numbers, so they are measured
    first and written down.
    """
    both = pd.concat(
        [
            frame[["long_pips", "long_end"]].rename(
                columns={"long_pips": "pips", "long_end": "end"}
            ),
            frame[["short_pips", "short_end"]].rename(
                columns={"short_pips": "pips", "short_end": "end"}
            ),
        ]
    )

    return {
        "sessions": int(len(frame)),
        "first": str(frame["fx_day"].min()),
        "last": str(frame["fx_day"].max()),
        "median_session_atr_pips": float(frame["session_atr_pips"].median()),
        "median_entry_spread_pips": float(frame["entry_spread_pips"].median()),
        "long": _side(frame, "long"),
        "short": _side(frame, "short"),
        "either_side": {
            "target_rate": float((both["end"] == "target").mean()),
            "stop_rate": float((both["end"] == "stop").mean()),
            "flat_rate": float((both["end"] == "flat").mean()),
            "mean_pips": float(both["pips"].mean()),
            "median_pips": float(both["pips"].median()),
        },
        "perfect_hindsight_mean_pips": float(
            frame[["long_pips", "short_pips"]].max(axis=1).mean()
        ),
        "always_long_mean_pips": float(frame["long_pips"].mean()),
        "always_short_mean_pips": float(frame["short_pips"].mean()),
    }


def _side(frame: pd.DataFrame, side: str) -> dict:
    ends = frame[f"{side}_end"]
    pips = frame[f"{side}_pips"]
    return {
        "target_rate": float((ends == "target").mean()),
        "stop_rate": float((ends == "stop").mean()),
        "flat_rate": float((ends == "flat").mean()),
        "mean_pips": float(pips.mean()),
        "median_pips": float(pips.median()),
        "total_pips": float(pips.sum()),
    }
