import lzma
import struct
from datetime import datetime, timezone

import pytest

from basis.sources import dukascopy as dk


def compress(records):
    raw = b"".join(dk.RECORD.pack(*r) for r in records)
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
    return compressor.compress(raw) + compressor.flush()


HOUR = datetime(2026, 8, 7, 13, tzinfo=timezone.utc)


def test_month_is_zero_indexed_in_the_url():
    assert dk.hour_url("EURUSD", datetime(2026, 1, 9, 5, tzinfo=timezone.utc)).endswith(
        "EURUSD/2026/00/09/05h_ticks.bi5"
    )
    assert dk.hour_url("EURUSD", datetime(2026, 12, 9, 5, tzinfo=timezone.utc)).endswith(
        "EURUSD/2026/11/09/05h_ticks.bi5"
    )


def test_august_maps_to_seven():
    assert "/2026/07/07/" in dk.hour_url("EURUSD", HOUR)


def test_decode_scales_points_and_offsets_from_the_hour():
    frame = dk.decode_hour(compress([(46, 115729, 115726, 0.9, 0.9)]), "EURUSD", HOUR)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["bid"] == pytest.approx(1.15726)
    assert row["ask"] == pytest.approx(1.15729)
    assert row["ts"] == datetime(2026, 8, 7, 13, 0, 0, 46000, tzinfo=timezone.utc)


def test_ask_is_never_below_bid_in_decoded_order():
    frame = dk.decode_hour(
        compress([(0, 115729, 115726, 1.0, 1.0), (500, 115740, 115739, 1.0, 1.0)]),
        "EURUSD",
        HOUR,
    )
    assert (frame["ask"] >= frame["bid"]).all()


def test_spread_is_recoverable_in_pips():
    frame = dk.decode_hour(compress([(0, 115760, 115726, 1.0, 1.0)]), "EURUSD", HOUR)
    spread_pips = (frame["ask"] - frame["bid"]).iloc[0] * 10_000
    assert spread_pips == pytest.approx(3.4, abs=1e-9)


def test_empty_payload_yields_typed_empty_frame():
    frame = dk.decode_hour(b"", "EURUSD", HOUR)
    assert frame.empty
    assert list(frame.columns) == ["ts", "bid", "ask", "bid_volume", "ask_volume"]


def test_truncated_record_is_rejected_rather_than_silently_dropped():
    payload = compress([(0, 115729, 115726, 1.0, 1.0)])
    raw = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(payload)
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
    truncated = compressor.compress(raw[:-4]) + compressor.flush()

    with pytest.raises(ValueError, match="whole number of ticks"):
        dk.decode_hour(truncated, "EURUSD", HOUR)


def test_timestamps_are_monotonic_within_the_hour():
    frame = dk.decode_hour(
        compress([(0, 1, 1, 0, 0), (1500, 1, 1, 0, 0), (3599999, 1, 1, 0, 0)]),
        "EURUSD",
        HOUR,
    )
    assert frame["ts"].is_monotonic_increasing
    assert frame["ts"].iloc[-1] < HOUR.replace(hour=14)
