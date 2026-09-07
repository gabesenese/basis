import time
from datetime import datetime, timedelta, timezone

import pytest

from basis.lanes.quote import MIN_INTERVAL_SECONDS, QuoteWriter, read_quote

BASE = datetime(2026, 8, 31, 11, 21, tzinfo=timezone.utc)


def tick(seconds=0, bid=1.16702, ask=1.16717, tradeable=True):
    return {
        "instrument": "EUR_USD",
        "ts": BASE + timedelta(seconds=seconds),
        "bid": bid,
        "ask": ask,
        "tradeable": tradeable,
    }


def test_a_written_quote_reads_back_with_its_mid_and_spread(tmp_path):
    path = tmp_path / "quote.json"
    QuoteWriter(path).offer(tick())

    quote = read_quote(path)

    assert quote["bid"] == 1.16702
    assert quote["ask"] == 1.16717
    assert quote["mid"] == pytest.approx(1.167095)
    assert quote["spread_pips"] == pytest.approx(1.5, abs=1e-9)
    assert quote["ts"] == BASE


def test_a_quote_inside_the_floor_is_dropped(tmp_path):
    path = tmp_path / "quote.json"
    writer = QuoteWriter(path, min_interval=10)

    assert writer.offer(tick()) is True
    assert writer.offer(tick(seconds=1, bid=1.2, ask=1.3)) is False
    assert read_quote(path)["bid"] == 1.16702


def test_a_quote_past_the_floor_overwrites_in_place(tmp_path):
    path = tmp_path / "quote.json"
    writer = QuoteWriter(path, min_interval=0)

    writer.offer(tick())
    writer.offer(tick(seconds=1, bid=1.16800, ask=1.16815))

    assert read_quote(path)["bid"] == 1.16800
    assert [p.name for p in tmp_path.iterdir()] == ["quote.json"]


def test_an_untradeable_quote_is_published_flagged(tmp_path):
    path = tmp_path / "quote.json"
    QuoteWriter(path).offer(tick(tradeable=False))

    assert read_quote(path)["tradeable"] is False


def test_a_locked_target_costs_the_quote_and_not_the_recorder(tmp_path, monkeypatch):
    path = tmp_path / "quote.json"
    writer = QuoteWriter(path, min_interval=0)
    writer.offer(tick())

    def refuse(self, target):
        raise OSError(32, "being used by another process")

    monkeypatch.setattr("pathlib.Path.replace", refuse)

    assert writer.offer(tick(seconds=1, bid=1.2, ask=1.3)) is False
    assert read_quote(path)["bid"] == 1.16702


def test_a_missing_file_reads_as_nothing(tmp_path):
    assert read_quote(tmp_path / "absent.json") is None


def test_a_half_written_file_reads_as_nothing(tmp_path):
    path = tmp_path / "quote.json"
    path.write_text('{"instrument": "EUR_USD", "bi', encoding="utf-8")

    assert read_quote(path) is None


def test_the_recorder_publishes_the_newest_tick_it_streamed(tmp_path, monkeypatch):
    pytest.importorskip("pandas")
    from basis.lanes import recorder as recorder_lane
    from basis.sources import oanda_stream

    def stream(instruments, stop=None, on_reconnect=None):
        yield {**tick(), "bid_volume": 500000, "ask_volume": 500000,
               "bid_depth": 2500000, "ask_depth": 2500000}
        time.sleep(MIN_INTERVAL_SECONDS * 2)
        yield {**tick(seconds=1, bid=1.16800, ask=1.16815), "bid_volume": 500000,
               "ask_volume": 500000, "bid_depth": 2500000, "ask_depth": 2500000}

    monkeypatch.setattr(oanda_stream, "stream", stream)

    quote_path = tmp_path / "var" / "quote.json"
    recorder_lane.Recorder(
        tmp_path / "parquet",
        "EUR_USD",
        tmp_path / "var" / "recorder.json",
        tmp_path / "var" / "recorder.log",
        quote_path,
    ).run()

    assert read_quote(quote_path)["bid"] == 1.16800


def test_a_recorder_given_no_quote_path_still_records(tmp_path, monkeypatch):
    pytest.importorskip("pandas")
    from basis.lanes import recorder as recorder_lane
    from basis.sources import oanda_stream

    def stream(instruments, stop=None, on_reconnect=None):
        yield {**tick(), "bid_volume": 500000, "ask_volume": 500000,
               "bid_depth": 2500000, "ask_depth": 2500000}

    monkeypatch.setattr(oanda_stream, "stream", stream)

    written = recorder_lane.Recorder(
        tmp_path / "parquet",
        "EUR_USD",
        tmp_path / "var" / "recorder.json",
        tmp_path / "var" / "recorder.log",
    ).run()

    assert written == 1
    assert not (tmp_path / "var" / "quote.json").exists()


class FakeConnection:
    """
    The bar fallback is the only branch of _spot that touches the database, and
    standing Postgres up to prove a fallback would make the cheapest test here
    depend on the most expensive fixture.
    """

    def __init__(self, row):
        self.row = row

    def execute(self, *_):
        return self

    def fetchone(self):
        return self.row


@pytest.fixture
def routes(tmp_path, monkeypatch):
    module = pytest.importorskip("basis.api.routes")
    monkeypatch.setattr(module.settings, "basis_var_root", str(tmp_path))
    monkeypatch.setattr(module.tick_lane, "latest_tick", lambda *_: None)
    return module


def test_the_live_quote_beats_a_flushed_tick_behind_it(routes, tmp_path, monkeypatch):
    QuoteWriter(tmp_path / "quote.json").offer(tick(seconds=90))
    monkeypatch.setattr(
        routes.tick_lane,
        "latest_tick",
        lambda *_: {"ts": BASE, "bid": 1.16000, "ask": 1.16015, "spread_pips": 1.5},
    )

    spot = routes._spot(None)

    assert spot["bid"] == 1.16702
    assert spot["as_of"] == BASE + timedelta(seconds=90)
    assert spot["source"] == "oanda stream"


def test_a_flushed_tick_beats_a_quote_left_behind_by_a_restart(routes, tmp_path, monkeypatch):
    QuoteWriter(tmp_path / "quote.json").offer(tick())
    monkeypatch.setattr(
        routes.tick_lane,
        "latest_tick",
        lambda *_: {
            "ts": BASE + timedelta(seconds=90),
            "bid": 1.16000,
            "ask": 1.16015,
            "spread_pips": 1.5,
        },
    )

    assert routes._spot(None)["bid"] == 1.16000


def test_with_neither_reading_the_last_bar_answers(routes):
    spot = routes._spot(
        FakeConnection({"effective_time": BASE, "bid_close": 1.16000, "ask_close": 1.16015})
    )

    assert spot["source"] == "oanda M1 bar"
    assert spot["spread_pips"] is None


def test_with_nothing_at_all_there_is_no_spot(routes):
    assert routes._spot(FakeConnection(None)) is None
