from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from basis.sources import atlanta_mpt

EASTERN = ZoneInfo("America/New_York")


def frame(**overrides) -> pd.DataFrame:
    row = {
        "Rate: mean": 400.0,
        "Rate: mode": 400.0,
        "Rate: 25th percentile": 380.0,
        "Rate: 75th percentile": 420.0,
        "Prob: cut": 20.0,
        "Prob: hike": 20.0,
        "Prob: 350bps - 375bps": 25.0,
        "Prob: 375bps - 400bps": 25.0,
        "Prob: 400bps - 425bps": 25.0,
        "Prob: 425bps - 450bps": 25.0,
    }
    row.update(overrides)

    built = pd.DataFrame([row])
    built.index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-27"), pd.Timestamp("2026-03-18"), "375bps - 400bps")],
        names=["date", "reference_start", "target_range"],
    )
    return built


def test_publication_lands_the_next_business_day_at_noon_eastern():
    assert atlanta_mpt.publication_time(date(2026, 8, 25)) == datetime(
        2026, 8, 26, 12, 0, tzinfo=EASTERN
    )


def test_a_friday_close_publishes_on_monday():
    assert atlanta_mpt.publication_time(date(2026, 8, 21)).date() == date(2026, 8, 24)


def test_a_holiday_pushes_publication_further_out():
    assert atlanta_mpt.publication_time(date(2025, 12, 24)).date() == date(2025, 12, 26)


def test_publication_never_precedes_the_close_it_describes():
    rows = atlanta_mpt.to_rows(frame())

    assert rows[0]["available_at"] > rows[0]["effective_time"]


def test_the_close_is_stamped_at_the_option_settlement():
    rows = atlanta_mpt.to_rows(frame())

    assert rows[0]["effective_time"] == datetime.combine(
        date(2026, 1, 27), time(15, 0), tzinfo=EASTERN
    )


def test_the_reference_window_is_what_identifies_the_expectation():
    rows = atlanta_mpt.to_rows(frame())

    assert rows[0]["event_key"] == "SOFR3M_2026-03-18"
    assert rows[0]["measure"] == atlanta_mpt.MEASURE


def test_dispersion_comes_from_the_bins_not_from_the_percentiles():
    rows = atlanta_mpt.to_rows(frame())
    distribution = rows[0]["distribution"]

    assert distribution["bin_mean_bps"] == pytest.approx(400.0)
    assert distribution["std_bps"] == pytest.approx(27.951, abs=0.001)
    assert distribution["bins"] == [
        [350.0, 375.0, 25.0],
        [375.0, 400.0, 25.0],
        [400.0, 425.0, 25.0],
        [425.0, 450.0, 25.0],
    ]


def test_the_prevailing_target_range_is_carried_through():
    distribution = atlanta_mpt.to_rows(frame())[0]["distribution"]

    assert (distribution["target_low_bps"], distribution["target_high_bps"]) == (
        375.0,
        400.0,
    )


def test_a_row_without_a_mean_is_dropped_rather_than_guessed():
    assert atlanta_mpt.to_rows(frame(**{"Rate: mean": float("nan")})) == []


def test_an_unparsed_target_range_raises_rather_than_ingesting():
    broken = frame()
    broken.index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-27"), pd.Timestamp("2026-03-18"), "unknown")],
        names=["date", "reference_start", "target_range"],
    )

    with pytest.raises(ValueError):
        atlanta_mpt.to_rows(broken)
