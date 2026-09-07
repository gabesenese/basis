from datetime import date, datetime, timezone

import httpx
import pandas as pd

SOURCE_ID = "yahoo_chart"

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

"""
An unofficial endpoint, and the source table records that in its
redistributable flag. It carries no service guarantee and can change shape
without notice, which is acceptable for a tool two people run and is not
acceptable under a live signal without a licensed source behind it.

Two measured facts shape this module.

Asking for `range=max` silently returns a coarser series than the interval
requested: the same call that answers 2,933 daily bars for an explicit period
answered 169 for four decades under range=max. Every call here therefore passes
period1 and period2 and the range parameter is never used.

And the series comes back already restated for splits. NVIDIA's close a week
before its ten for one split returns as 115.00 rather than 1150, so the prices
are expressed in units set by the most recent split. Returns are invariant under
that, which is why the study can use them, and the actions are collected beside
the bars so a later restatement is detectable rather than silent.
"""

HEADERS = {"User-Agent": "Mozilla/5.0"}


def open_client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=httpx.Timeout(30.0, read=60.0))


def _stamp(moment: date | datetime) -> int:
    if isinstance(moment, datetime):
        return int(moment.timestamp())
    return int(datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc).timestamp())


def fetch(
    client: httpx.Client,
    ticker: str,
    start: date,
    finish: date,
    interval: str = "1d",
) -> dict:
    response = client.get(
        f"{BASE}/{ticker}",
        params={
            "period1": _stamp(start),
            "period2": _stamp(finish),
            "interval": interval,
            "events": "split,div",
        },
    )
    response.raise_for_status()

    payload = response.json()["chart"]
    if payload.get("error"):
        raise RuntimeError(f"yahoo refused {ticker}: {payload['error']}")

    results = payload.get("result") or []
    if not results:
        raise RuntimeError(f"yahoo returned no series for {ticker}")
    return results[0]


def bars(result: dict) -> pd.DataFrame:
    """
    A session where the feed has a timestamp but no prices comes back with nulls
    across the quote arrays. Those rows are dropped rather than carried, because
    a bar with no close is not a quiet day, it is an absent one, and the
    difference matters to any gap detector reading the series later.
    """
    stamps = result.get("timestamp") or []
    if not stamps:
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume"]
        )

    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(stamps, unit="s", utc=True),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        }
    )
    frame = frame.dropna(subset=["open", "high", "low", "close"])

    """
    And a row whose low is not the lowest of its own four prices is dropped for
    the same reason a row with no close is: it is not a quiet session, it is
    not a session at all. Measured on Apple iSports Group, one bar in 2,516
    comes back with an open of 0.50 against a low of 3.50, on twenty shares
    traded. Thin names produce a handful of these and the feed does not mark
    them.

    Carrying one would mean either storing a bar that contradicts itself, which
    the table's own constraint refuses, or relaxing that constraint, which would
    let every later reader treat a high below the open as a real price. Dropping
    is the only option that leaves both the store and the series honest.
    """
    coherent = (
        (frame.low <= frame[["open", "high", "close"]].min(axis=1))
        & (frame.high >= frame[["open", "low", "close"]].max(axis=1))
    )
    frame = frame[coherent]

    return frame.reset_index(drop=True)


def actions(result: dict) -> list[dict]:
    """
    available_at is set to the effective date because this feed publishes no
    announcement date. That is deliberately late: a split is known to the market
    weeks before it takes effect, so a backtest reading this is withheld
    information it would really have had, which is the safe direction to be
    wrong in.
    """
    events = result.get("events") or {}
    rows = []

    for stamp, split in (events.get("splits") or {}).items():
        effective = datetime.fromtimestamp(int(stamp), timezone.utc).date()
        rows.append(
            {
                "action_type": "split",
                "effective_date": effective,
                "numerator": float(split["numerator"]),
                "denominator": float(split["denominator"]),
                "cash_amount": None,
            }
        )

    for stamp, dividend in (events.get("dividends") or {}).items():
        effective = datetime.fromtimestamp(int(stamp), timezone.utc).date()
        rows.append(
            {
                "action_type": "dividend",
                "effective_date": effective,
                "numerator": None,
                "denominator": None,
                "cash_amount": float(dividend["amount"]),
            }
        )

    return sorted(rows, key=lambda row: (row["effective_date"], row["action_type"]))


def split_factor(rows: list[dict], since: date | None = None) -> float:
    """
    The cumulative ratio the stored series is expressed in. Comparing this
    against a fresh fetch is what turns a silent restatement into a detected
    one: the same bars arriving ten times smaller is a units change, and it has
    to be a deliberate rewrite rather than an overwrite nobody saw.
    """
    factor = 1.0
    for row in rows:
        if row["action_type"] != "split":
            continue
        if since is not None and row["effective_date"] <= since:
            continue
        factor *= row["numerator"] / row["denominator"]
    return factor


def ingest_bars(
    conn, instrument_id: str, granularity: str, frame: pd.DataFrame
) -> int:
    if frame.empty:
        return 0

    rows = [
        (
            instrument_id,
            SOURCE_ID,
            granularity,
            row.ts.to_pydatetime(),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            None if pd.isna(row.volume) else int(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]

    with conn.cursor() as cursor:
        cursor.executemany(
            """
            insert into basis.equity_bar
              (instrument_id, source_id, granularity, effective_time,
               open, high, low, close, volume)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (instrument_id, source_id, granularity, effective_time)
            do nothing
            """,
            rows,
        )
        return cursor.rowcount


def ingest_actions(conn, instrument_id: str, rows: list[dict]) -> int:
    written = 0
    for row in rows:
        result = conn.execute(
            """
            insert into basis.corporate_action
              (instrument_id, source_id, action_type, effective_date,
               numerator, denominator, cash_amount, available_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (instrument_id, source_id, action_type, effective_date)
            do nothing
            """,
            (
                instrument_id,
                SOURCE_ID,
                row["action_type"],
                row["effective_date"],
                row["numerator"],
                row["denominator"],
                row["cash_amount"],
                datetime(
                    row["effective_date"].year,
                    row["effective_date"].month,
                    row["effective_date"].day,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        written += result.rowcount
    return written


def units_drift(conn, instrument_id: str, result: dict) -> str | None:
    """
    Reads the newest stored close against the same session in a fresh fetch. A
    ratio that is not one means the feed has restated the series since it was
    stored, which is a units migration and must be a decision rather than a
    surprise discovered inside a study.
    """
    stored = conn.execute(
        """
        select effective_time, close
        from basis.equity_bar
        where instrument_id = %s and source_id = %s and granularity = 'D'
        order by effective_time desc
        limit 1
        """,
        (instrument_id, SOURCE_ID),
    ).fetchone()
    if stored is None:
        return None

    frame = bars(result)
    match = frame[frame["ts"] == pd.Timestamp(stored["effective_time"])]
    if match.empty:
        return None

    fresh = float(match["close"].iloc[0])
    ratio = fresh / float(stored["close"])
    if abs(ratio - 1.0) < 1e-6:
        return None

    return (
        f"{instrument_id}: a serie foi reapresentada, "
        f"{stored['close']} armazenado contra {fresh} agora, razao {ratio:.6f}"
    )
