from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from basis.lanes import spread_model, ticks as tick_lane
from basis.lanes.tick_writer import TickWriter

EVENT = datetime(2026, 7, 29, 18, tzinfo=timezone.utc)


def synthetic_event(baseline_pips: float, peak_pips: float, event=EVENT):
    """Quiet half hour, anticipatory widening, a spike, then decay."""
    rows = []
    for offset in range(-1800, -60, 3):
        rows.append((offset, baseline_pips))
    for offset in range(-60, -5):
        rows.append((offset, baseline_pips * 1.7))
    for offset in range(-5, 0):
        rows.append((offset, baseline_pips * 3.0))
    for offset in range(0, 2):
        rows.append((offset, peak_pips))
    for offset in range(2, 5):
        rows.append((offset, peak_pips * 0.6))
    for offset in range(5, 40):
        rows.append((offset, baseline_pips * 2.3))
    for offset in range(40, 900, 2):
        rows.append((offset, baseline_pips * 1.3))

    half = [
        {
            "ts": event + timedelta(seconds=offset),
            "bid": 1.16000,
            "ask": 1.16000 + spread / 10000,
            "bid_volume": 1.0,
            "ask_volume": 1.0,
        }
        for offset, spread in rows
    ]
    return half


@pytest.fixture
def con(tmp_path):
    with TickWriter(tmp_path, "dukascopy", "EURUSD", flush_rows=100000) as writer:
        for tick in synthetic_event(0.30, 8.00):
            writer.add(tick)
    connection = tick_lane.connect(tmp_path)
    yield connection
    connection.close()


def test_profile_is_expressed_as_a_multiple_of_the_baseline(con):
    profile = spread_model.measure_profile(con, [EVENT], "dukascopy", "EURUSD")
    release = profile[profile["bucket_from"] == 0].iloc[0]

    assert release["median_ratio"] == pytest.approx(8.0 / 0.3, rel=0.02)


def test_profile_is_invariant_to_the_venue_baseline(tmp_path):
    """A venue quoting five times wider must yield the same shape."""
    profiles = []
    for index, (base, peak) in enumerate([(0.30, 8.00), (1.50, 40.00)]):
        root = tmp_path / f"v{index}"
        with TickWriter(root, "dukascopy", "EURUSD", flush_rows=100000) as writer:
            for tick in synthetic_event(base, peak):
                writer.add(tick)
        profiles.append(
            spread_model.measure_profile(tick_lane.connect(root), [EVENT], "dukascopy", "EURUSD")
        )

    merged = profiles[0].merge(profiles[1], on="bucket_from", suffixes=("_a", "_b"))
    assert (merged["median_ratio_a"] - merged["median_ratio_b"]).abs().max() < 0.01


def test_quiet_window_is_the_reference_and_sits_at_one(con):
    profile = spread_model.measure_profile(con, [EVENT], "dukascopy", "EURUSD")
    quiet = profile[profile["bucket_from"] == -300].iloc[0]

    assert quiet["median_ratio"] == pytest.approx(1.0, abs=0.05)


def test_an_event_without_enough_quiet_history_is_skipped(tmp_path):
    with TickWriter(tmp_path, "dukascopy", "EURUSD", flush_rows=100000) as writer:
        for tick in synthetic_event(0.30, 8.00)[-50:]:
            writer.add(tick)

    profile = spread_model.measure_profile(
        tick_lane.connect(tmp_path), [EVENT], "dukascopy", "EURUSD"
    )
    assert profile.empty


def test_estimate_scales_the_shape_onto_another_baseline(con):
    profile = spread_model.measure_profile(con, [EVENT], "dukascopy", "EURUSD")
    estimate = spread_model.estimate(profile, baseline_pips=1.50, seconds_from_event=1)

    assert estimate.pips > 30
    assert estimate.provenance == "modelled"
    assert estimate.measured is False


def test_estimate_says_so_when_no_profile_exists():
    estimate = spread_model.estimate(pd.DataFrame(), baseline_pips=1.50, seconds_from_event=1)

    assert estimate.provenance == "unavailable"
    assert estimate.measured is False


def test_estimate_outside_the_measured_window_is_still_marked(con):
    profile = spread_model.measure_profile(con, [EVENT], "dukascopy", "EURUSD")
    estimate = spread_model.estimate(profile, baseline_pips=1.50, seconds_from_event=99999)

    assert estimate.provenance == "modelled"
    assert "outside" in estimate.basis


def test_estimate_carries_a_readable_basis(con):
    profile = spread_model.measure_profile(con, [EVENT], "dukascopy", "EURUSD")
    estimate = spread_model.estimate(profile, baseline_pips=1.50, seconds_from_event=1)

    assert "dukascopy shape" in estimate.basis
    assert "1.50 pip baseline" in estimate.basis
