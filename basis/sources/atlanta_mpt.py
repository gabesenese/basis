import re
from datetime import date, datetime, time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from psycopg.types.json import Jsonb

SOURCE_ID = "atlanta_mpt"
DATA_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "cenfis/market-probability-tracker/mpt_histdata.xlsx"
)

EASTERN = ZoneInfo("America/New_York")
MEASURE = "avg_sofr_bps"

"""
The distribution is estimated from CME three month SOFR options, which settle
at 15:00 Eastern, so that instant is what the observation date describes.

Publication runs a day behind the close. The workbook fetched on 2026-08-26
answered with an HTTP Last-Modified of 10:22 Eastern that morning and carried
observations through the 25th. Noon on the next business day therefore sits
after the publication actually observed, and still ahead of a 14:00 Eastern
statement, so the distribution from the eve of a meeting stays usable at the
meeting without being credited earlier than it existed.
"""
SETTLEMENT_CLOCK = time(15, 0)
PUBLICATION_CLOCK = time(12, 0)

_BIN = re.compile(r"^Prob: (\d+)bps - (\d+)bps$")
_TARGET_RANGE = re.compile(r"^(\d+)bps - (\d+)bps$")

_holidays = {
    d.date()
    for d in USFederalHolidayCalendar().holidays(start="2000-01-01", end="2035-12-31")
}


def publication_time(observation_date: date) -> datetime:
    day = observation_date + timedelta(days=1)
    while day.weekday() >= 5 or day in _holidays:
        day += timedelta(days=1)
    return datetime.combine(day, PUBLICATION_CLOCK, tzinfo=EASTERN)


def fetch(url: str = DATA_URL, client: httpx.Client | None = None) -> bytes:
    owned = client is None
    client = client or httpx.Client(timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.content
    finally:
        if owned:
            client.close()


def parse(content: bytes | str) -> pd.DataFrame:
    """
    The workbook ships one row per statistic. Pivoting to one row per
    observation and reference window is what makes a distribution addressable
    as a single fact, which is the grain the expectation table stores.
    """
    source = BytesIO(content) if isinstance(content, bytes) else content
    long = pd.read_excel(source, sheet_name="DATA")
    long["date"] = pd.to_datetime(long["date"])
    long["reference_start"] = pd.to_datetime(long["reference_start"])

    return long.pivot_table(
        index=["date", "reference_start", "target_range"],
        columns="field",
        values="value",
    )


def _bins(row: pd.Series) -> list[list[float]]:
    found = []
    for field, value in row.items():
        match = _BIN.match(str(field))
        if match and pd.notna(value):
            found.append([float(match.group(1)), float(match.group(2)), float(value)])
    found.sort()
    return found


def _dispersion(bins: list[list[float]]) -> tuple[float, float]:
    mass = sum(probability for _, _, probability in bins)
    if mass <= 0:
        return float("nan"), float("nan")

    midpoints = [(low + high) / 2 for low, high, _ in bins]
    weights = [probability / mass for _, _, probability in bins]
    mean = sum(w * m for w, m in zip(weights, midpoints))
    variance = sum(w * (m - mean) ** 2 for w, m in zip(weights, midpoints))
    return mean, variance**0.5


def to_rows(frame: pd.DataFrame) -> list[dict]:
    rows = []

    for (observed, reference_start, target_range), row in frame.iterrows():
        mean = row.get("Rate: mean")
        if pd.isna(mean):
            continue

        target = _TARGET_RANGE.match(str(target_range))
        if target is None:
            raise ValueError(f"unparsed target range: {target_range!r}")

        bins = _bins(row)
        bin_mean, bin_std = _dispersion(bins)
        observation_date = observed.date()

        rows.append(
            {
                "event_key": f"SOFR3M_{reference_start.date().isoformat()}",
                "measure": MEASURE,
                "effective_time": datetime.combine(
                    observation_date, SETTLEMENT_CLOCK, tzinfo=EASTERN
                ),
                "available_at": publication_time(observation_date),
                "point_value": float(mean),
                "distribution": {
                    "reference_start": reference_start.date().isoformat(),
                    "observation_date": observation_date.isoformat(),
                    "mean_bps": float(mean),
                    "mode_bps": _optional(row.get("Rate: mode")),
                    "p25_bps": _optional(row.get("Rate: 25th percentile")),
                    "p75_bps": _optional(row.get("Rate: 75th percentile")),
                    "bin_mean_bps": _optional(bin_mean),
                    "std_bps": _optional(bin_std),
                    "prob_cut": _optional(row.get("Prob: cut")),
                    "prob_hike": _optional(row.get("Prob: hike")),
                    "target_low_bps": float(target.group(1)),
                    "target_high_bps": float(target.group(2)),
                    "bins": bins,
                },
            }
        )

    return rows


def _optional(value):
    return None if value is None or pd.isna(value) else float(value)


def ingest(conn, rows: list[dict]) -> int:
    written = 0
    for row in rows:
        result = conn.execute(
            """
            insert into basis.expectation
              (event_key, source_id, measure, effective_time, available_at,
               point_value, distribution)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (event_key, source_id, measure, effective_time, available_at)
            do nothing
            """,
            (
                row["event_key"],
                SOURCE_ID,
                row["measure"],
                row["effective_time"],
                row["available_at"],
                row["point_value"],
                Jsonb(row["distribution"]),
            ),
        )
        written += result.rowcount
    return written
