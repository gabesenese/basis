from datetime import date, datetime, timezone

import pandas as pd
import pytest
from psycopg.rows import dict_row

from basis.sources import yahoo

SPLIT_STAMP = int(datetime(2024, 6, 10, tzinfo=timezone.utc).timestamp())
DIV_STAMP = int(datetime(2024, 6, 11, tzinfo=timezone.utc).timestamp())

RESULT = {
    "timestamp": [
        int(datetime(2024, 6, 3, tzinfo=timezone.utc).timestamp()),
        int(datetime(2024, 6, 4, tzinfo=timezone.utc).timestamp()),
        int(datetime(2024, 6, 5, tzinfo=timezone.utc).timestamp()),
    ],
    "indicators": {
        "quote": [
            {
                "open": [114.0, 115.0, None],
                "high": [116.0, 117.0, None],
                "low": [113.0, 114.0, None],
                "close": [115.0, 116.44, None],
                "volume": [438392000, 403324000, None],
            }
        ]
    },
    "events": {
        "splits": {
            str(SPLIT_STAMP): {
                "date": SPLIT_STAMP,
                "numerator": 10.0,
                "denominator": 1.0,
                "splitRatio": "10:1",
            }
        },
        "dividends": {str(DIV_STAMP): {"amount": 0.01, "date": DIV_STAMP}},
    },
}


def test_a_session_with_no_prices_is_dropped_rather_than_carried():
    """
    A bar with a timestamp and null prices is an absent session, not a quiet
    one. Carrying it would make a gap detector read silence as data.
    """
    frame = yahoo.bars(RESULT)

    assert len(frame) == 2
    assert frame["close"].notna().all()


def test_bars_come_back_with_an_aware_index():
    frame = yahoo.bars(RESULT)

    assert frame["ts"].dt.tz is not None


def test_an_empty_series_is_an_empty_frame_rather_than_a_raise():
    frame = yahoo.bars({"timestamp": [], "indicators": {"quote": [{}]}})

    assert frame.empty
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]


def test_splits_and_dividends_are_both_read():
    rows = yahoo.actions(RESULT)

    kinds = sorted(row["action_type"] for row in rows)
    assert kinds == ["dividend", "split"]


def test_a_split_carries_its_ratio_and_a_dividend_carries_its_amount():
    rows = {row["action_type"]: row for row in yahoo.actions(RESULT)}

    assert rows["split"]["numerator"] == 10.0
    assert rows["split"]["denominator"] == 1.0
    assert rows["split"]["cash_amount"] is None
    assert rows["dividend"]["cash_amount"] == 0.01
    assert rows["dividend"]["numerator"] is None


def test_a_result_with_no_events_returns_no_actions():
    assert yahoo.actions({"timestamp": [1]}) == []


def test_the_cumulative_split_factor_multiplies_every_split():
    rows = [
        {"action_type": "split", "effective_date": date(2021, 7, 20),
         "numerator": 4.0, "denominator": 1.0},
        {"action_type": "split", "effective_date": date(2024, 6, 10),
         "numerator": 10.0, "denominator": 1.0},
        {"action_type": "dividend", "effective_date": date(2024, 6, 11),
         "cash_amount": 0.01},
    ]

    assert yahoo.split_factor(rows) == 40.0
    assert yahoo.split_factor(rows, since=date(2021, 7, 20)) == 10.0
    assert yahoo.split_factor(rows, since=date(2024, 6, 10)) == 1.0


def test_range_is_never_sent_because_it_returns_a_coarser_series():
    """
    Asking for range=max silently answers a coarser interval than the one
    requested, which is how the same call returned 169 bars for four decades
    and 2,933 for an explicit period. Nothing here may reintroduce it.
    """
    import inspect

    source = inspect.getsource(yahoo.fetch)

    assert '"range"' not in source
    assert "period1" in source and "period2" in source


def test_units_drift_reports_a_restated_series(db_conn):
    """
    The guard that makes a split visible. A stored series ten times larger than
    a fresh fetch is the same prices in different units, and it has to surface
    as a decision rather than be silently half overwritten.
    """
    db_conn.row_factory = dict_row
    db_conn.execute(
        "insert into basis.source (id, kind, publisher, redistributable) "
        "values (%s, 'price', 'test', false) on conflict (id) do nothing",
        (yahoo.SOURCE_ID,),
    )
    db_conn.execute(
        "insert into basis.instrument "
        "(id, base_ccy, quote_ccy, pip_size, asset_class, display_name) "
        "values ('TESTCO', null, 'USD', 0.01, 'equity', 'Test Co') "
        "on conflict (id) do nothing"
    )
    moment = datetime(2024, 6, 4, tzinfo=timezone.utc)
    db_conn.execute(
        "insert into basis.equity_bar "
        "(instrument_id, source_id, granularity, effective_time, open, high, low, close) "
        "values ('TESTCO', %s, 'D', %s, 1150, 1170, 1140, 1164.4)",
        (yahoo.SOURCE_ID, moment),
    )

    message = yahoo.units_drift(db_conn, "TESTCO", RESULT)

    assert message is not None
    assert "reapresentada" in message


def test_units_drift_is_quiet_when_the_series_agrees(db_conn):
    db_conn.row_factory = dict_row
    db_conn.execute(
        "insert into basis.source (id, kind, publisher, redistributable) "
        "values (%s, 'price', 'test', false) on conflict (id) do nothing",
        (yahoo.SOURCE_ID,),
    )
    db_conn.execute(
        "insert into basis.instrument "
        "(id, base_ccy, quote_ccy, pip_size, asset_class, display_name) "
        "values ('TESTCO2', null, 'USD', 0.01, 'equity', 'Test Co 2') "
        "on conflict (id) do nothing"
    )
    moment = datetime(2024, 6, 4, tzinfo=timezone.utc)
    db_conn.execute(
        "insert into basis.equity_bar "
        "(instrument_id, source_id, granularity, effective_time, open, high, low, close) "
        "values ('TESTCO2', %s, 'D', %s, 115, 117, 114, 116.44)",
        (yahoo.SOURCE_ID, moment),
    )

    assert yahoo.units_drift(db_conn, "TESTCO2", RESULT) is None


def test_units_drift_is_quiet_on_an_instrument_with_no_stored_bars(db_conn):
    db_conn.row_factory = dict_row
    assert yahoo.units_drift(db_conn, "NOTHING_STORED", RESULT) is None


@pytest.mark.live
def test_the_real_series_is_already_restated_for_splits():
    """
    NVIDIA split ten for one in June 2024. A close near 1150 a week before it
    would mean the feed serves the units of the day; a close near 115 means the
    series is restated, which is what the collector assumes.
    """
    with yahoo.open_client() as client:
        result = yahoo.fetch(client, "NVDA", date(2024, 6, 3), date(2024, 6, 8))

    frame = yahoo.bars(result)
    assert not frame.empty
    assert frame["close"].max() < 200


@pytest.mark.live
def test_an_explicit_period_returns_daily_bars_rather_than_a_coarser_series():
    with yahoo.open_client() as client:
        result = yahoo.fetch(client, "AAPL", date(2024, 1, 1), date(2024, 12, 31))

    frame = yahoo.bars(result)
    gaps = frame["ts"].diff().dropna().dt.days

    assert len(frame) > 240
    assert gaps.max() <= 5


@pytest.mark.live
def test_an_unknown_ticker_raises_rather_than_returning_an_empty_series():
    with yahoo.open_client() as client:
        with pytest.raises((RuntimeError, Exception)):
            yahoo.fetch(client, "NOT_A_REAL_TICKER_XYZ", date(2024, 1, 1), date(2024, 2, 1))
