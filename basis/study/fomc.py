from datetime import timedelta

import pandas as pd

from basis.sources import atlanta_mpt

INSTRUMENT = "EUR_USD"
PIP = 0.0001

HORIZONS = {
    "5m": timedelta(minutes=5),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "1d": timedelta(days=1),
}

BAR_TOLERANCE = timedelta(minutes=10)
DAILY_TOLERANCE = timedelta(hours=6)


def meetings(conn) -> list[dict]:
    """
    The latest vintage of each event key, which is the schedule as it finally
    stood. A meeting moved and then held is studied at the instant it actually
    happened, while the expectation is still read as of that instant.
    """
    return conn.execute(
        """
        select distinct on (event_key) event_key, scheduled_time
        from basis.calendar_event
        where event_code = 'FOMC_DECISION'
        order by event_key, available_at desc
        """
    ).fetchall()


def distributions(conn) -> pd.DataFrame:
    rows = conn.execute(
        """
        select event_key, effective_time, available_at, point_value, distribution
        from basis.expectation
        where source_id = %s and measure = %s
        """,
        (atlanta_mpt.SOURCE_ID, atlanta_mpt.MEASURE),
    ).fetchall()

    frame = pd.DataFrame(rows)
    unpacked = pd.json_normalize(frame.pop("distribution"))
    frame = pd.concat([frame, unpacked], axis=1)
    frame["reference_start"] = pd.to_datetime(frame["reference_start"]).dt.date
    frame["observation_date"] = pd.to_datetime(frame["observation_date"]).dt.date
    return frame


def _mid_at(conn, moment, tolerance: timedelta) -> float | None:
    """
    A bar carries the minute that starts at its effective_time, so the price at
    an instant is the close of the bar that ends there, not the one that opens
    there. Reading the opening bar would put the release inside the price we
    call pre release.
    """
    closes_at = moment - timedelta(minutes=1)
    row = conn.execute(
        """
        select (bid_close + ask_close) / 2 as mid
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
          and effective_time <= %s and effective_time >= %s
        order by effective_time desc
        limit 1
        """,
        (INSTRUMENT, closes_at, closes_at - tolerance),
    ).fetchone()
    return float(row["mid"]) if row else None


def _excursion(conn, start, finish, entry: float) -> tuple[float | None, float | None]:
    row = conn.execute(
        """
        select min((bid_low + ask_low) / 2) as low,
               max((bid_high + ask_high) / 2) as high
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
          and effective_time >= %s and effective_time < %s
        """,
        (INSTRUMENT, start, finish),
    ).fetchone()

    if row is None or row["low"] is None:
        return None, None
    return (
        (float(row["low"]) - entry) / PIP,
        (float(row["high"]) - entry) / PIP,
    )


def _pre_release(frame: pd.DataFrame, statement_time) -> pd.Series | None:
    """
    Everything published before the statement, then the newest observation in
    it, then the first reference window that opens after the meeting. Filtering
    on available_at rather than on the observation date is what keeps a
    distribution that was still unpublished at 14:00 out of the expectation.
    """
    known = frame[frame["available_at"] <= statement_time]
    if known.empty:
        return None

    latest = known[known["observation_date"] == known["observation_date"].max()]
    ahead = latest[latest["reference_start"] >= statement_time.date()]
    if ahead.empty:
        return None

    return ahead.sort_values("reference_start").iloc[0]


def _post_release(frame: pd.DataFrame, statement_time, reference_start) -> pd.Series | None:
    """
    The first observation after the meeting date, which is where the target
    range is read. The workbook stamps a decision onto the meeting date itself
    in some years and onto the following day in others, so only the day after
    is certain to carry the range the decision actually set.
    """
    later = frame[
        (frame["observation_date"] > statement_time.date())
        & (frame["reference_start"] == reference_start)
    ]
    if later.empty:
        return None
    return later.sort_values("observation_date").iloc[0]


def _same_day(frame: pd.DataFrame, statement_time, reference_start) -> pd.Series | None:
    """
    The close on the meeting day, 15:00 Eastern, one hour after the statement.
    It is the tightest repricing window this source can express: the day before
    against the hour after. The day after would fold an overnight session and a
    second trading day into a number meant to carry one announcement.
    """
    same = frame[
        (frame["observation_date"] == statement_time.date())
        & (frame["reference_start"] == reference_start)
    ]
    return None if same.empty else same.iloc[0]


def build(conn) -> pd.DataFrame:
    frame = distributions(conn)
    records = []

    for meeting in meetings(conn):
        statement_time = meeting["scheduled_time"]

        pre = _pre_release(frame, statement_time)
        if pre is None or pd.isna(pre["std_bps"]) or pre["std_bps"] <= 0:
            continue

        post = _post_release(frame, statement_time, pre["reference_start"])
        if post is None:
            continue

        same = _same_day(frame, statement_time, pre["reference_start"])

        entry = _mid_at(conn, statement_time, BAR_TOLERANCE)
        if entry is None:
            continue

        mid_before = (pre["target_low_bps"] + pre["target_high_bps"]) / 2
        mid_after = (post["target_low_bps"] + post["target_high_bps"]) / 2

        actual_bps = mid_after - mid_before
        expected_bps = float(pre["mean_bps"]) - mid_before
        std_bps = float(pre["std_bps"])

        record = {
            "event_key": meeting["event_key"],
            "statement_time": statement_time,
            "reference_start": pre["reference_start"],
            "observed_pre": pre["observation_date"],
            "observed_post": post["observation_date"],
            "expectation_available_at": pre["available_at"],
            "window_lead_days": (pre["reference_start"] - statement_time.date()).days,
            "target_mid_before": mid_before,
            "target_mid_after": mid_after,
            "actual_bps": actual_bps,
            "expected_bps": expected_bps,
            "surprise_bps": actual_bps - expected_bps,
            "std_bps": std_bps,
            "z_actual": actual_bps / std_bps,
            "z_expected": expected_bps / std_bps,
            "z_surprise": (actual_bps - expected_bps) / std_bps,
            "reprice_bps": None if same is None else float(same["mean_bps"]) - float(pre["mean_bps"]),
            "z_reprice": None
            if same is None
            else (float(same["mean_bps"]) - float(pre["mean_bps"])) / std_bps,
            "reprice_next_bps": float(post["mean_bps"]) - float(pre["mean_bps"]),
            "z_reprice_next": (float(post["mean_bps"]) - float(pre["mean_bps"])) / std_bps,
            "prob_cut": pre["prob_cut"],
            "prob_hike": pre["prob_hike"],
            "entry_mid": entry,
        }

        for name, offset in HORIZONS.items():
            tolerance = DAILY_TOLERANCE if offset >= timedelta(days=1) else BAR_TOLERANCE
            exit_mid = _mid_at(conn, statement_time + offset, tolerance)
            record[f"ret_{name}"] = (
                None if exit_mid is None else (exit_mid - entry) / PIP
            )

        low, high = _excursion(
            conn, statement_time, statement_time + HORIZONS["2h"], entry
        )
        record["excursion_low_2h"] = low
        record["excursion_high_2h"] = high

        records.append(record)

    return pd.DataFrame(records).sort_values("statement_time").reset_index(drop=True)
