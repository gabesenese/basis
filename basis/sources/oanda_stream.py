import json
import time
from datetime import datetime, timezone

import httpx

from basis.config import settings
from basis.sources.oanda import STREAM_HOSTS

SOURCE_ID = "oanda_stream"

RECONNECT_BACKOFF = [1, 2, 5, 10, 30]
STALE_AFTER_SECONDS = 30


def _url() -> str:
    host = STREAM_HOSTS[settings.oanda_environment]
    return f"{host}/v3/accounts/{settings.oanda_account_id}/pricing/stream"


def parse_price(message: dict) -> dict | None:
    """
    Only the top of book is kept as bid and ask, because that is where an order
    of our size fills. The deeper rungs are kept as liquidity so a later
    size-aware cost model has something to work from without a second capture.
    """
    bids = message.get("bids") or []
    asks = message.get("asks") or []
    if not bids or not asks:
        return None

    return {
        "ts": datetime.fromisoformat(message["time"].replace("Z", "+00:00")),
        "bid": float(bids[0]["price"]),
        "ask": float(asks[0]["price"]),
        "bid_volume": float(bids[0].get("liquidity", 0)),
        "ask_volume": float(asks[0].get("liquidity", 0)),
        "bid_depth": sum(float(level.get("liquidity", 0)) for level in bids),
        "ask_depth": sum(float(level.get("liquidity", 0)) for level in asks),
        "tradeable": bool(message.get("tradeable", True)),
    }


def stream(instruments: list[str] | None = None, stop=None, on_reconnect=None):
    """
    Yields ticks forever, reconnecting on its own.

    A silent socket is indistinguishable from a quiet market from the outside,
    so OANDA sends heartbeats and this treats their absence as a dead
    connection rather than as calm. Reconnecting on silence is what keeps a
    recorder from writing an hour of nothing and calling it data.

    Reconnections are reported through on_reconnect rather than logged here,
    because a generator that runs for months has no business deciding where its
    operator reads about it. A caller that ignores the callback loses nothing.
    """
    instruments = instruments or ["EUR_USD"]
    attempt = 0

    while stop is None or not stop():
        last_message = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, read=STALE_AFTER_SECONDS)) as client:
                with client.stream(
                    "GET",
                    _url(),
                    headers={"Authorization": f"Bearer {settings.oanda_api_token}"},
                    params={"instruments": ",".join(instruments)},
                ) as response:
                    response.raise_for_status()
                    attempt = 0

                    for line in response.iter_lines():
                        if stop is not None and stop():
                            return
                        if time.monotonic() - last_message > STALE_AFTER_SECONDS:
                            break
                        if not line.strip():
                            continue

                        last_message = time.monotonic()
                        message = json.loads(line)
                        if message.get("type") != "PRICE":
                            continue

                        tick = parse_price(message)
                        if tick:
                            tick["instrument"] = message.get("instrument", instruments[0])
                            yield tick
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = "stream ended or went silent"

        delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
        attempt += 1

        if on_reconnect is not None:
            on_reconnect(reason, delay)

        time.sleep(delay)
