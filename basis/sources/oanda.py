from datetime import datetime

import httpx
import pandas as pd

from basis.config import settings

SOURCE_ID = "oanda"

REST_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
STREAM_HOSTS = {
    "practice": "https://stream-fxpractice.oanda.com",
    "live": "https://stream-fxtrade.oanda.com",
}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.oanda_api_token}",
        "Accept-Datetime-Format": "RFC3339",
    }


def open_client(stream: bool = False) -> httpx.Client:
    hosts = STREAM_HOSTS if stream else REST_HOSTS
    return httpx.Client(
        base_url=hosts[settings.oanda_environment],
        headers=_headers(),
        timeout=httpx.Timeout(30.0, read=60.0),
    )


def accounts(client: httpx.Client) -> list[dict]:
    response = client.get("/v3/accounts")
    response.raise_for_status()
    return response.json()["accounts"]


def candles(
    client: httpx.Client,
    instrument: str = "EUR_USD",
    granularity: str = "M5",
    count: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    complete_only: bool = True,
) -> pd.DataFrame:
    """
    The newest candle of any request that reaches the present is still forming
    and comes back with complete false. Treating it as a finished bar reads a
    partial window as if it had closed, so it is dropped unless asked for.

    Daily granularity is pinned to midnight UTC. OANDA otherwise aligns the day
    to 17:00 New York, which would silently disagree with every other source
    here.
    """
    params: dict = {"price": "BA", "granularity": granularity}
    if count is not None:
        params["count"] = count
    if start is not None:
        params["from"] = start.isoformat().replace("+00:00", "Z")
    if end is not None:
        params["to"] = end.isoformat().replace("+00:00", "Z")
    if granularity.startswith("D") or granularity.startswith("W"):
        params["alignmentTimezone"] = "UTC"
        params["dailyAlignment"] = 0

    response = client.get(f"/v3/instruments/{instrument}/candles", params=params)
    response.raise_for_status()
    payload = response.json()["candles"]

    if complete_only:
        payload = [c for c in payload if c["complete"]]

    if not payload:
        return _empty_candles()

    frame = pd.DataFrame(
        [
            {
                "ts": c["time"],
                "bid_open": float(c["bid"]["o"]),
                "bid_high": float(c["bid"]["h"]),
                "bid_low": float(c["bid"]["l"]),
                "bid_close": float(c["bid"]["c"]),
                "ask_open": float(c["ask"]["o"]),
                "ask_high": float(c["ask"]["h"]),
                "ask_low": float(c["ask"]["l"]),
                "ask_close": float(c["ask"]["c"]),
                "tick_count": int(c["volume"]),
            }
            for c in payload
        ]
    )
    frame["ts"] = pd.to_datetime(frame["ts"], format="ISO8601", utc=True)
    return frame


def _empty_candles() -> pd.DataFrame:
    columns = [
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    ]
    frame = pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns, UTC]")})
    for column in columns:
        frame[column] = pd.Series(dtype="float64")
    frame["tick_count"] = pd.Series(dtype="int64")
    return frame


def pricing(client: httpx.Client, instruments: list[str] | None = None) -> list[dict]:
    response = client.get(
        f"/v3/accounts/{settings.oanda_account_id}/pricing",
        params={"instruments": ",".join(instruments or ["EUR_USD"])},
    )
    response.raise_for_status()

    return [
        {
            "instrument": price["instrument"],
            "ts": pd.Timestamp(price["time"]),
            "bid": float(price["bids"][0]["price"]),
            "ask": float(price["asks"][0]["price"]),
            "tradeable": price["tradeable"],
        }
        for price in response.json()["prices"]
    ]


MAX_CANDLES = 5000


def backfill(
    client: httpx.Client,
    instrument: str,
    granularity: str,
    start: datetime,
    end: datetime,
    on_page=None,
):
    """
    Pages forward from the last candle received rather than by a fixed stride,
    because weekends and holidays make the calendar span of a page vary. Pages
    are yielded as they arrive so the caller can write incrementally instead of
    holding a decade of bars in memory.
    """
    cursor = start

    while cursor < end:
        page = candles(
            client,
            instrument=instrument,
            granularity=granularity,
            start=cursor,
            count=MAX_CANDLES,
        )
        page = page[page["ts"] < pd.Timestamp(end)]
        if page.empty:
            return

        yield page
        if on_page:
            on_page(page)

        last = page["ts"].max().to_pydatetime()
        if last <= cursor:
            return
        cursor = last + pd.Timedelta(seconds=1)
