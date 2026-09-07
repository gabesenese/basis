from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from basis.lanes import bars as bars_lane

START = datetime(2026, 8, 25, 10, tzinfo=timezone.utc)


def frame(count: int, offset: int = 0) -> pd.DataFrame:
    rows = [
        {
            "ts": START + timedelta(minutes=i + offset),
            "bid_open": 1.1000, "bid_high": 1.1010, "bid_low": 1.0990, "bid_close": 1.1005,
            "ask_open": 1.1002, "ask_high": 1.1012, "ask_low": 1.0992, "ask_close": 1.1007,
            "tick_count": 42,
        }
        for i in range(count)
    ]
    built = pd.DataFrame(rows)
    built["ts"] = pd.to_datetime(built["ts"], utc=True)
    return built


@pytest.fixture
def prepared(db_conn):
    db_conn.execute(
        "insert into basis.source (id, kind, publisher, redistributable) "
        "values ('test_price', 'price', 'test', false) on conflict (id) do nothing"
    )
    db_conn.execute(
        "insert into basis.instrument "
        "(id, base_ccy, quote_ccy, pip_size, asset_class, display_name) "
        "values ('TEST_PAIR', 'EUR', 'USD', 0.0001, 'fx', 'TEST/PAIR') "
        "on conflict (id) do nothing"
    )
    return db_conn


def stored(conn) -> int:
    return conn.execute(
        "select count(*) from basis.price_bar where instrument_id = 'TEST_PAIR'"
    ).fetchone()[0]


def test_bars_load_through_staging(prepared):
    written = bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(500))

    assert written == 500
    assert stored(prepared) == 500


def test_reloading_the_same_window_writes_nothing(prepared):
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(100))
    again = bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(100))

    assert again == 0
    assert stored(prepared) == 100


def test_overlapping_pages_insert_only_the_new_bars(prepared):
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(100))
    written = bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(100, offset=60))

    assert written == 60
    assert stored(prepared) == 160


def test_the_same_minute_at_another_granularity_is_a_separate_bar(prepared):
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(10))
    written = bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M5", frame(10))

    assert written == 10
    assert stored(prepared) == 20


def test_empty_frame_is_a_no_op(prepared):
    assert bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", pd.DataFrame()) == 0


def test_staging_table_does_not_survive_the_load(prepared):
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(10))
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(10, offset=10))

    assert stored(prepared) == 20


def test_ask_stays_above_bid_through_the_round_trip(prepared):
    bars_lane.ingest(prepared, "TEST_PAIR", "test_price", "M1", frame(20))
    bad = prepared.execute(
        "select count(*) from basis.price_bar "
        "where instrument_id = 'TEST_PAIR' and ask_close < bid_close"
    ).fetchone()[0]

    assert bad == 0
