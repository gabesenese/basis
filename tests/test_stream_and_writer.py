from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from basis.lanes.tick_writer import TickWriter
from basis.sources import oanda_stream


def price_message(bid="1.16702", ask="1.16717", tradeable=True):
    return {
        "type": "PRICE",
        "instrument": "EUR_USD",
        "time": "2026-08-25T17:43:19.994946642Z",
        "tradeable": tradeable,
        "bids": [
            {"price": bid, "liquidity": 500000},
            {"price": "1.16700", "liquidity": 2000000},
        ],
        "asks": [
            {"price": ask, "liquidity": 500000},
            {"price": "1.16719", "liquidity": 2000000},
        ],
    }


def test_top_of_book_becomes_bid_and_ask():
    tick = oanda_stream.parse_price(price_message())

    assert tick["bid"] == 1.16702
    assert tick["ask"] == 1.16717
    assert tick["bid_volume"] == 500000


def test_deeper_rungs_are_kept_as_depth():
    tick = oanda_stream.parse_price(price_message())

    assert tick["bid_depth"] == 2500000
    assert tick["ask_depth"] == 2500000


def test_nanosecond_timestamp_parses_to_utc():
    tick = oanda_stream.parse_price(price_message())

    assert tick["ts"].tzinfo is not None
    assert tick["ts"].astimezone(timezone.utc).hour == 17


def test_untradeable_quote_is_flagged_not_dropped():
    tick = oanda_stream.parse_price(price_message(tradeable=False))

    assert tick["tradeable"] is False


def test_a_message_with_no_book_is_rejected():
    assert oanda_stream.parse_price({"type": "PRICE", "time": "x", "bids": [], "asks": []}) is None


BASE = datetime(2026, 8, 25, 17, 44, tzinfo=timezone.utc)


def tick(offset_seconds: int) -> dict:
    return {
        "ts": BASE + timedelta(seconds=offset_seconds),
        "bid": 1.16700, "ask": 1.16715,
        "bid_volume": 500000.0, "ask_volume": 500000.0,
        "bid_depth": 2500000.0, "ask_depth": 2500000.0,
        "tradeable": True,
    }


def test_writer_flushes_when_the_buffer_fills(tmp_path):
    writer = TickWriter(tmp_path, "oanda_stream", "EUR_USD", flush_rows=5, flush_seconds=9999)
    for i in range(4):
        assert writer.add(tick(i)) is False
    assert writer.add(tick(4)) is True
    assert writer.written == 5


def test_writer_holds_a_partial_buffer_until_closed(tmp_path):
    with TickWriter(tmp_path, "oanda_stream", "EUR_USD", flush_rows=100, flush_seconds=9999) as w:
        for i in range(3):
            w.add(tick(i))
        assert w.written == 0
    assert w.written == 3


def test_flushing_an_empty_buffer_writes_nothing(tmp_path):
    writer = TickWriter(tmp_path, "oanda_stream", "EUR_USD")
    assert writer.flush() is False
    assert list(tmp_path.rglob("*.parquet")) == []


def test_a_buffer_spanning_midnight_lands_in_two_days(tmp_path):
    writer = TickWriter(tmp_path, "oanda_stream", "EUR_USD", flush_rows=100, flush_seconds=9999)
    midnight = datetime(2026, 8, 25, 23, 59, 30, tzinfo=timezone.utc)
    for offset in (0, 60):
        writer.add({**tick(0), "ts": midnight + timedelta(seconds=offset)})
    writer.flush()

    days = sorted(p.name[:10] for p in tmp_path.rglob("*.parquet"))
    assert days == ["2026-08-25", "2026-08-26"]


def test_chunks_do_not_overwrite_each_other(tmp_path):
    writer = TickWriter(tmp_path, "oanda_stream", "EUR_USD", flush_rows=2, flush_seconds=9999)
    for i in range(6):
        writer.add(tick(i))

    assert len(list(tmp_path.rglob("*.parquet"))) == 3
    assert writer.written == 6


def test_written_chunks_are_readable_as_one_series(tmp_path):
    from basis.lanes import ticks as tick_lane

    writer = TickWriter(tmp_path, "oanda_stream", "EUR_USD", flush_rows=2, flush_seconds=9999)
    for i in range(6):
        writer.add(tick(i))

    con = tick_lane.connect(tmp_path)
    total = con.execute("select count(*) from ticks where source = 'oanda_stream'").fetchone()[0]
    assert total == 6
