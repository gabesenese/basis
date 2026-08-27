from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from basis.lanes import ticks
from basis.sources import dukascopy as dk

RELEASE = datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc)


def synthetic_day() -> pd.DataFrame:
    """
    A quiet hour at a 0.2 pip spread, a release at 13:30 where the spread blows
    out to 9 pips for ninety seconds and price jumps, then a calm tail with a
    deliberate two minute hole to exercise gap detection.
    """
    rows = []
    moment = datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc)
    price = 1.15700

    while moment < RELEASE:
        rows.append((moment, price - 0.00001, price + 0.00001))
        moment += timedelta(seconds=1)

    for offset in range(90):
        widening = 0.00045 if offset < 20 else 0.00009
        price += 0.00004
        rows.append((RELEASE + timedelta(seconds=offset), price - widening, price + widening))

    moment = RELEASE + timedelta(seconds=90)
    while moment < RELEASE + timedelta(minutes=10):
        if timedelta(minutes=3) <= moment - RELEASE < timedelta(minutes=5):
            moment += timedelta(seconds=1)
            continue
        rows.append((moment, price - 0.00002, price + 0.00002))
        moment += timedelta(seconds=1)

    frame = pd.DataFrame(rows, columns=["ts", "bid", "ask"])
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame["bid_volume"] = 1.0
    frame["ask_volume"] = 1.0
    return frame


@pytest.fixture
def con(tmp_path):
    dk.write_day(tmp_path, "EURUSD", date(2026, 8, 7), synthetic_day())
    connection = ticks.connect(tmp_path)
    yield connection
    connection.close()


def test_partition_layout_is_hive_readable(tmp_path):
    path = dk.write_day(tmp_path, "EURUSD", date(2026, 8, 7), synthetic_day())
    assert path.parent.name == "year=2026"
    assert path.parent.parent.name == "symbol=EURUSD"


def test_spot_as_of_never_returns_a_future_tick(con):
    quiet = ticks.spot_as_of(con, "EURUSD", RELEASE - timedelta(seconds=1))
    assert quiet["ts"] <= RELEASE - timedelta(seconds=1)
    assert quiet["spread_pips"] == pytest.approx(0.2, abs=0.01)


def test_spot_as_of_before_any_data_returns_nothing(con):
    assert ticks.spot_as_of(con, "EURUSD", datetime(2026, 8, 7, 12, tzinfo=timezone.utc)) is None


def test_spread_blows_out_at_the_release_and_recovers(con):
    profile = ticks.spread_profile(
        con, "EURUSD", RELEASE - timedelta(minutes=2), RELEASE + timedelta(minutes=3), 30
    )
    profile = profile.set_index("bucket")["max_pips"]

    before = profile[profile.index < pd.Timestamp(RELEASE)].max()
    at_release = profile[profile.index == pd.Timestamp(RELEASE)].iloc[0]

    assert before == pytest.approx(0.2, abs=0.01)
    assert at_release == pytest.approx(9.0, abs=0.01)
    assert at_release / before > 40


def test_cost_hurdle_would_reject_entry_inside_the_dead_window(con):
    at_release = ticks.spot_as_of(con, "EURUSD", RELEASE + timedelta(seconds=5))
    after_window = ticks.spot_as_of(con, "EURUSD", RELEASE + timedelta(seconds=95))

    assert at_release["spread_pips"] > 5
    assert after_window["spread_pips"] < 1


def test_bars_aggregate_bid_and_ask_separately(con):
    frame = ticks.bars(con, "EURUSD", RELEASE, RELEASE + timedelta(minutes=1), 60)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["ask_high"] > row["bid_high"]
    assert row["bid_low"] <= row["bid_open"] <= row["bid_high"]
    assert row["tick_count"] == 60


def test_gap_detection_finds_the_hole(con):
    found = ticks.gaps(
        con, "EURUSD", RELEASE, RELEASE + timedelta(minutes=10), threshold_seconds=30
    )

    assert len(found) == 1
    assert found.iloc[0]["gap_seconds"] == pytest.approx(121, abs=1)
