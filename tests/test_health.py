from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from basis.lanes import health

EASTERN = ZoneInfo("America/New_York")


class FakeConnection:
    def __init__(self, newest):
        self.newest = newest

    def execute(self, *_):
        return self

    def fetchone(self):
        return {"newest": self.newest}


def eastern(year, month, day, hour):
    return datetime(year, month, day, hour, tzinfo=EASTERN)


def beating(path, moment, last_tick=None, written=100):
    beat = health.Heartbeat(
        instrument="EUR_USD",
        started_at=moment - timedelta(hours=1),
        last_tick_at=last_tick,
        ticks_written=written,
    )
    beat.write(path)
    beat.updated_at = moment
    path.write_text(beat.as_json(), encoding="utf-8")
    return beat


def test_saturday_is_closed():
    assert not health.market_open(eastern(2026, 8, 22, 12))


def test_friday_afternoon_closes_at_five():
    assert health.market_open(eastern(2026, 8, 21, 16))
    assert not health.market_open(eastern(2026, 8, 21, 18))


def test_sunday_evening_opens_at_five():
    assert not health.market_open(eastern(2026, 8, 23, 16))
    assert health.market_open(eastern(2026, 8, 23, 18))


def test_midweek_is_open_around_the_clock():
    assert all(health.market_open(eastern(2026, 8, 19, hour)) for hour in range(24))


def test_a_missing_heartbeat_is_reported_rather_than_assumed_healthy(tmp_path):
    report = health.inspect(
        FakeConnection(datetime.now(timezone.utc)), tmp_path / "absent.json"
    )

    assert not report.healthy
    assert any(f.subject == "recorder" and not f.healthy for f in report.findings)


def test_a_stale_heartbeat_fails_even_with_the_market_closed(tmp_path):
    moment = eastern(2026, 8, 22, 12).astimezone(timezone.utc)
    path = tmp_path / "recorder.json"
    beating(path, moment - timedelta(minutes=30))

    report = health.inspect(FakeConnection(moment), path, moment=moment)
    recorder = next(f for f in report.findings if f.subject == "recorder")

    assert not recorder.healthy


def test_silence_is_healthy_when_the_market_is_closed(tmp_path):
    moment = eastern(2026, 8, 22, 12).astimezone(timezone.utc)
    path = tmp_path / "recorder.json"
    beating(path, moment, last_tick=moment - timedelta(hours=20))

    report = health.inspect(FakeConnection(moment), path, moment=moment)
    ticks = next(f for f in report.findings if f.subject == "ticks")

    assert ticks.healthy
    assert "market closed" in ticks.detail


def test_silence_is_a_failure_while_the_market_is_open(tmp_path):
    moment = eastern(2026, 8, 19, 12).astimezone(timezone.utc)
    path = tmp_path / "recorder.json"
    beating(path, moment, last_tick=moment - timedelta(minutes=30))

    report = health.inspect(FakeConnection(moment), path, moment=moment)
    ticks = next(f for f in report.findings if f.subject == "ticks")

    assert not ticks.healthy


def test_a_flowing_recorder_and_fresh_bars_report_healthy(tmp_path):
    moment = eastern(2026, 8, 19, 12).astimezone(timezone.utc)
    path = tmp_path / "recorder.json"
    beating(path, moment, last_tick=moment - timedelta(seconds=5))

    report = health.inspect(
        FakeConnection(moment - timedelta(minutes=2)), path, moment=moment
    )

    assert report.healthy


def test_bars_a_week_old_fail_on_their_own(tmp_path):
    moment = eastern(2026, 8, 19, 12).astimezone(timezone.utc)
    path = tmp_path / "recorder.json"
    beating(path, moment, last_tick=moment - timedelta(seconds=5))

    report = health.inspect(
        FakeConnection(moment - timedelta(days=7)), path, moment=moment
    )
    bars = next(f for f in report.findings if f.subject == "bars")

    assert not bars.healthy
    assert not report.healthy


def test_the_heartbeat_round_trips_through_disk(tmp_path):
    path = tmp_path / "recorder.json"
    moment = datetime.now(timezone.utc)
    beat = health.Heartbeat(
        instrument="EUR_USD", started_at=moment, last_tick_at=moment, ticks_written=7
    )
    beat.write(path)

    restored = health.read_heartbeat(path)

    assert restored["ticks_written"] == 7
    assert restored["instrument"] == "EUR_USD"
    assert restored["updated_at"].tzinfo is not None


def test_a_truncated_heartbeat_reads_as_absent_rather_than_raising(tmp_path):
    path = tmp_path / "recorder.json"
    path.write_text('{"instrument": "EUR', encoding="utf-8")

    assert health.read_heartbeat(path) is None


def test_writing_leaves_no_staging_file_behind(tmp_path):
    path = tmp_path / "recorder.json"
    health.Heartbeat(
        instrument="EUR_USD", started_at=datetime.now(timezone.utc)
    ).write(path)

    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "gap, expected",
    [(timedelta(seconds=30), "30s ago"), (timedelta(minutes=5), "5m ago"),
     (timedelta(hours=3), "3h ago"), (None, "never")],
)
def test_ages_read_as_plain_english(gap, expected):
    assert health._spell(gap) == expected
