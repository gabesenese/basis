import lzma
import struct
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

SOURCE_ID = "dukascopy"
FEED_ROOT = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">IIIff")

"""
The feed drops connections from clients that do not present a browser user
agent. It does so by timing out rather than answering, so an unadorned client
looks like a network fault instead of a policy block.
"""
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAX_ATTEMPTS = 5

"""
Throttling shows up in three different disguises: a connection that times out,
a 503, and a socket closed mid-response. All three mean slow down, none of them
mean the hour is missing, so all three retry rather than surface as a gap.
"""
_RETRYABLE = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)

"""
The feed answers 503 when polled too fast, and measured behaviour is that a
handful of requests in quick succession is already enough to trip it. Backoff
alone does not recover: five attempts reaching 32 seconds still came back 503.

A decade of one instrument is roughly 87,600 hourly files, so at this interval
the backfill is a multi-day resumable job rather than something that runs in an
afternoon. That is a property of the source, not of this code, and the reason
backfill() skips partitions that already exist.
"""
MIN_INTERVAL = 2.5
_last_request = 0.0


class FeedThrottled(RuntimeError):
    """
    Raised when an hour could not be retrieved because the feed pushed back.

    Deliberately distinct from an empty result. An empty hour is a fact about
    the market, a weekend or a holiday, and belongs in the data as a gap. A
    throttled hour is a fact about the connection and must be retried, never
    recorded as if the market had been silent.
    """


def _pace() -> None:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()

POINT_SCALE = {"EURUSD": 100_000, "USDJPY": 1_000, "USDCAD": 100_000, "USDBRL": 100_000}


def hour_url(symbol: str, moment: datetime) -> str:
    """
    Dukascopy numbers months from zero, so January is 00 and December is 11.
    Passing a calendar month here silently returns the wrong month of data
    rather than failing, which is why the conversion lives in one place.
    """
    return (
        f"{FEED_ROOT}/{symbol}/{moment.year:04d}/{moment.month - 1:02d}"
        f"/{moment.day:02d}/{moment.hour:02d}h_ticks.bi5"
    )


def decode_hour(payload: bytes, symbol: str, hour_start: datetime) -> pd.DataFrame:
    if not payload:
        return _empty_frame()

    raw = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(payload)
    if len(raw) % RECORD.size:
        raise ValueError(f"{symbol} {hour_start:%Y-%m-%d %H}: {len(raw)} bytes is not a whole number of ticks")

    scale = POINT_SCALE[symbol]
    rows = [
        (
            hour_start + timedelta(milliseconds=offset),
            bid / scale,
            ask / scale,
            bid_volume,
            ask_volume,
        )
        for offset, ask, bid, ask_volume, bid_volume in RECORD.iter_unpack(raw)
    ]

    frame = pd.DataFrame(rows, columns=["ts", "bid", "ask", "bid_volume", "ask_volume"])
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.Series(dtype="datetime64[ns, UTC]"),
            "bid": pd.Series(dtype="float64"),
            "ask": pd.Series(dtype="float64"),
            "bid_volume": pd.Series(dtype="float64"),
            "ask_volume": pd.Series(dtype="float64"),
        }
    )


def open_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(30.0, connect=15.0),
        headers={"User-Agent": BROWSER_UA},
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
    )


def fetch_hour(client: httpx.Client, symbol: str, hour_start: datetime) -> pd.DataFrame:
    url = hour_url(symbol, hour_start)
    for attempt in range(MAX_ATTEMPTS):
        _pace()
        try:
            response = client.get(url)
        except _RETRYABLE as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise FeedThrottled(f"{url}: {type(exc).__name__}") from exc
            time.sleep(2**attempt)
            continue

        if response.status_code == 404:
            return _empty_frame()
        if response.status_code in (429, 503) or response.status_code >= 500:
            if attempt == MAX_ATTEMPTS - 1:
                raise FeedThrottled(f"{url} answered {response.status_code}")
            time.sleep(2 ** (attempt + 1))
            continue

        response.raise_for_status()
        return decode_hour(response.content, symbol, hour_start)

    return _empty_frame()


def fetch_day(symbol: str, day: date, client: httpx.Client | None = None) -> pd.DataFrame:
    owned = client is None
    client = client or open_client()
    try:
        frames = [
            fetch_hour(
                client,
                symbol,
                datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc),
            )
            for hour in range(24)
        ]
    finally:
        if owned:
            client.close()

    populated = [f for f in frames if not f.empty]
    return pd.concat(populated, ignore_index=True) if populated else _empty_frame()


def write_day(root: Path, symbol: str, day: date, frame: pd.DataFrame) -> Path | None:
    from basis.lanes.ticks import partition_path

    if frame.empty:
        return None
    target = partition_path(root, SOURCE_ID, symbol, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False, compression="zstd")
    return target


def backfill(root: Path, symbol: str, start: date, end: date, overwrite: bool = False):
    written = []
    with open_client() as client:
        day = start
        while day <= end:
            from basis.lanes.ticks import partition_path

            target = partition_path(root, SOURCE_ID, symbol, day)
            if target.exists() and not overwrite:
                day += timedelta(days=1)
                continue
            frame = fetch_day(symbol, day, client=client)
            path = write_day(root, symbol, day, frame)
            if path:
                written.append((day, len(frame)))
            day += timedelta(days=1)
    return written
