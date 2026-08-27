from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from pandas.tseries.holiday import USFederalHolidayCalendar

SOURCE_ID = "cftc"
DATASET_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
EURO_FX_CODE = "099741"

EASTERN = ZoneInfo("America/New_York")
RELEASE_CLOCK = time(15, 30)

_holidays = {
    d.date()
    for d in USFederalHolidayCalendar().holidays(start="2000-01-01", end="2035-12-31")
}


def release_time(report_date: date) -> datetime:
    """
    The report covers positions at Tuesday close and publishes the following
    Friday at 15:30 Eastern. Each federal holiday falling anywhere in the
    report week, or between the report date and the nominal release, pushes the
    release one business day later.

    The window deliberately spans the whole report week rather than only the
    days after the report date. Over-delaying costs nothing for a weekly context
    feature, while a missed delay would place available_at before the true
    publication and leak the future.

    Where the true publication instant is unknown, the derived one is moved
    later rather than earlier. A late available_at only hides data we might
    have had; an early one leaks the future into the backtest.
    """
    nominal = report_date + timedelta(days=(4 - report_date.weekday()) % 7 or 7)
    week_opens = report_date - timedelta(days=6)

    delays = 0
    day = week_opens
    while day <= nominal:
        if day.weekday() < 5 and day in _holidays:
            delays += 1
        day += timedelta(days=1)

    release = nominal
    for _ in range(delays):
        release += timedelta(days=1)
        while release.weekday() >= 5 or release in _holidays:
            release += timedelta(days=1)

    return datetime.combine(release, RELEASE_CLOCK, tzinfo=EASTERN)


def fetch(contract_code: str = EURO_FX_CODE, since: date | None = None, limit: int = 5000):
    where = [f"cftc_contract_market_code='{contract_code}'"]
    if since:
        where.append(f"report_date_as_yyyy_mm_dd>='{since.isoformat()}'")

    response = httpx.get(
        DATASET_URL,
        params={
            "$where": " AND ".join(where),
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": limit,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def to_rows(payload: list[dict], contract_code: str = EURO_FX_CODE):
    rows = []
    for item in payload:
        report_date = datetime.fromisoformat(item["report_date_as_yyyy_mm_dd"]).date()
        effective_time = datetime.combine(report_date, time(20, 0), tzinfo=ZoneInfo("UTC"))
        metrics = {
            key: float(item[key])
            for key in (
                "open_interest_all",
                "noncomm_positions_long_all",
                "noncomm_positions_short_all",
                "comm_positions_long_all",
                "comm_positions_short_all",
            )
            if item.get(key) is not None
        }
        metrics["noncomm_net"] = (
            metrics.get("noncomm_positions_long_all", 0.0)
            - metrics.get("noncomm_positions_short_all", 0.0)
        )
        rows.append(
            {
                "contract_code": contract_code,
                "effective_time": effective_time,
                "available_at": release_time(report_date),
                "metrics": metrics,
            }
        )
    return rows


def ingest(conn, rows: list[dict]) -> int:
    written = 0
    for row in rows:
        result = conn.execute(
            """
            insert into basis.positioning
              (contract_code, source_id, effective_time, available_at, metrics)
            values (%s, %s, %s, %s, %s)
            on conflict (contract_code, effective_time, available_at) do nothing
            """,
            (
                row["contract_code"],
                SOURCE_ID,
                row["effective_time"],
                row["available_at"],
                psycopg_json(row["metrics"]),
            ),
        )
        written += result.rowcount
    return written


def psycopg_json(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
