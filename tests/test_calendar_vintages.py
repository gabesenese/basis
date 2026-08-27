from datetime import datetime, timedelta, timezone

import pytest

from basis.lanes import calendar as calendar_lane

KEY = "TEST_EVENT_2026-09-10"
BASE = datetime(2026, 9, 10, 12, 15, tzinfo=timezone.utc)


def row(scheduled, available):
    return {
        "event_key": KEY,
        "region": "EA",
        "event_code": "TEST",
        "scheduled_time": scheduled,
        "available_at": available,
        "payload": {},
    }


@pytest.fixture
def source(db_conn):
    db_conn.execute(
        """
        insert into basis.source (id, kind, publisher, redistributable)
        values ('test_calendar', 'calendar', 'test', true)
        on conflict (id) do nothing
        """
    )
    return "test_calendar"


def scheduled_times(conn):
    return [
        r[0]
        for r in conn.execute(
            "select scheduled_time from basis.calendar_event "
            "where event_key = %s order by available_at",
            (KEY,),
        ).fetchall()
    ]


def test_rescraping_an_unchanged_calendar_writes_nothing(db_conn, source):
    first = calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=200))])
    second = calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=100))])

    assert (first, second) == (1, 0)
    assert scheduled_times(db_conn) == [BASE]


def test_a_reschedule_creates_a_new_vintage(db_conn, source):
    moved = BASE + timedelta(hours=1)
    calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=200))])
    written = calendar_lane.ingest(db_conn, source, [row(moved, BASE - timedelta(days=30))])

    assert written == 1
    assert scheduled_times(db_conn) == [BASE, moved]


def test_as_of_before_the_reschedule_still_sees_the_old_time(db_conn, source):
    moved = BASE + timedelta(hours=1)
    calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=200))])
    calendar_lane.ingest(db_conn, source, [row(moved, BASE - timedelta(days=30))])

    def seen_at(as_of):
        found = db_conn.execute(
            "select scheduled_time from basis.calendar_as_of(%s, %s, %s) where event_key = %s",
            (as_of, BASE - timedelta(days=365), BASE + timedelta(days=1), KEY),
        ).fetchone()
        return found[0] if found else None

    assert seen_at(BASE - timedelta(days=100)) == BASE
    assert seen_at(BASE - timedelta(days=10)) == moved


def test_a_meeting_moved_back_registers_the_return(db_conn, source):
    moved = BASE + timedelta(hours=1)
    calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=200))])
    calendar_lane.ingest(db_conn, source, [row(moved, BASE - timedelta(days=100))])
    written = calendar_lane.ingest(db_conn, source, [row(BASE, BASE - timedelta(days=20))])

    assert written == 1
    assert scheduled_times(db_conn) == [BASE, moved, BASE]
