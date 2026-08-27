from datetime import datetime, timezone

import pandas as pd
import pytest

from basis.sources import oanda


def candle(time_iso, bid_close, ask_close, complete=True, volume=10):
    return {
        "complete": complete,
        "volume": volume,
        "time": time_iso,
        "bid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": str(bid_close)},
        "ask": {"o": "1.1", "h": "1.2", "l": "1.0", "c": str(ask_close)},
    }


class FakeResponse:
    def __init__(self, payload, recorder=None):
        self._payload = payload
        self.recorder = recorder

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params or {}))
        return FakeResponse(self.payload)


def test_incomplete_candle_is_dropped_by_default():
    client = FakeClient(
        {"candles": [
            candle("2026-08-25T17:20:00.000000000Z", 1.1669, 1.16706),
            candle("2026-08-25T17:25:00.000000000Z", 1.1670, 1.16714, complete=False),
        ]}
    )
    frame = oanda.candles(client)

    assert len(frame) == 1
    assert frame["ts"].iloc[0] == pd.Timestamp("2026-08-25T17:20:00Z")


def test_incomplete_candle_is_available_on_request():
    client = FakeClient(
        {"candles": [
            candle("2026-08-25T17:20:00.000000000Z", 1.1669, 1.16706),
            candle("2026-08-25T17:25:00.000000000Z", 1.1670, 1.16714, complete=False),
        ]}
    )
    assert len(oanda.candles(client, complete_only=False)) == 2


def test_a_page_of_only_incomplete_candles_is_empty_not_malformed():
    client = FakeClient(
        {"candles": [candle("2026-08-25T17:25:00.000000000Z", 1.1, 1.1, complete=False)]}
    )
    frame = oanda.candles(client)

    assert frame.empty
    assert "bid_close" in frame.columns


def test_bid_and_ask_are_requested_separately():
    client = FakeClient({"candles": []})
    oanda.candles(client)

    assert client.calls[0][1]["price"] == "BA"


def test_daily_granularity_is_pinned_to_utc_midnight():
    client = FakeClient({"candles": []})
    oanda.candles(client, granularity="D")

    params = client.calls[0][1]
    assert params["alignmentTimezone"] == "UTC"
    assert params["dailyAlignment"] == 0


def test_intraday_granularity_does_not_send_alignment():
    client = FakeClient({"candles": []})
    oanda.candles(client, granularity="M5")

    assert "alignmentTimezone" not in client.calls[0][1]


def test_timestamps_parse_to_utc():
    client = FakeClient(
        {"candles": [candle("2026-08-25T17:20:00.000000000Z", 1.1669, 1.16706)]}
    )
    frame = oanda.candles(client)

    assert frame["ts"].dt.tz is not None
    assert str(frame["ts"].dt.tz) == "UTC"


class PagingClient:
    """Two full pages then an empty one, mirroring the end of a backfill."""

    def __init__(self):
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse({"candles": [
                candle("2026-08-25T10:00:00.000000000Z", 1.1, 1.1),
                candle("2026-08-25T10:01:00.000000000Z", 1.1, 1.1),
            ]})
        if self.calls == 2:
            return FakeResponse({"candles": [
                candle("2026-08-25T10:02:00.000000000Z", 1.1, 1.1),
            ]})
        return FakeResponse({"candles": []})


def test_backfill_pages_forward_and_stops_when_dry():
    client = PagingClient()
    pages = list(
        oanda.backfill(
            client, "EUR_USD", "M1",
            datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 11, tzinfo=timezone.utc),
        )
    )

    assert [len(p) for p in pages] == [2, 1]
    assert client.calls == 3


def test_backfill_never_yields_past_the_requested_end():
    client = PagingClient()
    pages = list(
        oanda.backfill(
            client, "EUR_USD", "M1",
            datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 10, 2, tzinfo=timezone.utc),
        )
    )

    assert all((page["ts"] < pd.Timestamp("2026-08-25T10:02:00Z")).all() for page in pages)
