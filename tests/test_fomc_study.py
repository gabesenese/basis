from datetime import datetime, timedelta, timezone

import pytest

from basis import db
from basis.study import fomc


@pytest.fixture(scope="module")
def study():
    """
    Reads the collected history rather than a fixture, because the property
    under test is whether the as-of discipline holds against the real data.
    A synthetic meeting would prove only that the filter compiles.
    """
    psycopg = pytest.importorskip("psycopg")

    try:
        with db.connect() as conn:
            frame = fomc.build(conn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    if frame.empty:
        pytest.skip("no FOMC meetings collected yet")
    return frame


def test_no_expectation_was_read_before_it_was_published(study):
    late = study[study["expectation_available_at"] > study["statement_time"]]

    assert late.empty, late[["event_key", "expectation_available_at"]].to_string()


def test_the_expectation_predates_the_statement_it_is_measured_against(study):
    assert (study["observed_pre"] < study["statement_time"].dt.date).all()


def test_the_target_range_is_read_after_the_decision_not_at_it(study):
    assert (study["observed_post"] > study["statement_time"].dt.date).all()


def test_the_reference_window_opens_at_or_after_the_meeting(study):
    assert (study["window_lead_days"] >= 0).all()


def test_the_entry_price_is_the_minute_that_ends_at_the_statement(study):
    with db.connect() as conn:
        for _, meeting in study.iterrows():
            statement = meeting["statement_time"]
            row = conn.execute(
                """
                select (bid_close + ask_close) / 2 as mid
                from basis.price_bar
                where instrument_id = %s and granularity = 'M1'
                  and effective_time = %s
                """,
                (fomc.INSTRUMENT, statement - timedelta(minutes=1)),
            ).fetchone()

            if row is not None:
                assert meeting["entry_mid"] == pytest.approx(float(row["mid"]))


def test_the_bar_that_opens_on_the_release_is_never_the_entry():
    """
    The minute that starts at the statement already carries the reaction. Two
    bars are planted around an instant no real backfill covers, one closing on
    it and one opening on it, and the reader must take the first.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    from basis.config import settings

    moment = datetime(2019, 6, 19, 18, 0, tzinfo=timezone.utc)

    try:
        conn = psycopg.connect(
            settings.basis_database_url, row_factory=dict_row, connect_timeout=3
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    try:
        for offset, price in ((timedelta(minutes=-1), 1.1000), (timedelta(0), 1.2000)):
            conn.execute(
                """
                insert into basis.price_bar
                  (instrument_id, source_id, granularity, effective_time,
                   bid_open, bid_high, bid_low, bid_close,
                   ask_open, ask_high, ask_low, ask_close)
                values (%s, 'oanda', 'M1', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (fomc.INSTRUMENT, moment + offset, *[price] * 8),
            )

        assert fomc._mid_at(conn, moment, fomc.BAR_TOLERANCE) == pytest.approx(1.1000)
    finally:
        conn.rollback()
        conn.close()


def test_the_decision_is_a_whole_number_of_moves(study):
    assert (study["actual_bps"] % 25 == 0).all()


def test_dispersion_is_positive_wherever_a_meeting_is_scored(study):
    assert (study["std_bps"] > 0).all()
