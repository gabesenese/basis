from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from basis.lanes import expectation, fundamentals
from basis.study import earnings


def moment(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def fact(period_start, period_end, value, available_at, unit="USD"):
    return {
        "period_start": date.fromisoformat(period_start),
        "period_end": date.fromisoformat(period_end),
        "span_days": (
            date.fromisoformat(period_end) - date.fromisoformat(period_start)
        ).days,
        "value": Decimal(str(value)),
        "available_at": moment(available_at),
        "form": "10-Q",
        "accession": f"{period_end}-{available_at}",
        "concept": "Revenues",
        "unit": unit,
    }


def split(effective, ratio):
    return {
        "effective_date": date.fromisoformat(effective),
        "numerator": Decimal(str(ratio)),
        "denominator": Decimal("1"),
        "available_at": moment(f"{effective}T00:00:00"),
    }


def test_the_fourth_quarter_is_the_year_minus_the_nine_months_inside_it():
    """
    No quarterly report covers the fourth quarter, so reading only ninety day
    durations drops one release in four, and the one it drops is the annual.
    """
    rows = [
        fact("2024-01-01", "2024-09-30", 90, "2024-10-25T12:00:00"),
        fact("2024-01-01", "2024-12-31", 130, "2025-02-10T12:00:00"),
    ]

    derived = fundamentals._derived_quarters(rows, [])

    assert len(derived) == 1
    assert derived[0]["period_end"] == date(2024, 12, 31)
    assert derived[0]["period_start"] == date(2024, 9, 30)
    assert derived[0]["value"] == pytest.approx(40)
    assert derived[0]["origin"] == "derived"


def test_a_derived_quarter_is_knowable_only_when_the_annual_figure_is():
    rows = [
        fact("2024-01-01", "2024-09-30", 90, "2024-10-25T12:00:00"),
        fact("2024-01-01", "2024-12-31", 130, "2025-02-10T12:00:00"),
    ]

    derived = fundamentals._derived_quarters(rows, [])

    assert derived[0]["available_at"] == moment("2025-02-10T12:00:00")


def test_a_derived_quarter_refuses_a_stub_reported_after_the_year():
    """
    A nine month figure restated after the 10-K was filed was not available
    when the annual one was, and subtracting it would mix vintages.
    """
    rows = [
        fact("2024-01-01", "2024-12-31", 130, "2025-02-10T12:00:00"),
        fact("2024-01-01", "2024-09-30", 95, "2025-10-25T12:00:00"),
    ]

    assert fundamentals._derived_quarters(rows, []) == []


def test_per_share_facts_are_restated_into_the_units_of_the_reading_instant():
    """
    NVIDIA's quarter to April 2024 was filed at 5.98 a share and is 0.60 after
    the ten for one split in June. Reading the filed number against a later
    quarter compares a number to a tenth of itself.
    """
    rows = [fact("2024-02-01", "2024-04-28", "5.98", "2024-05-29T12:00:00", "USD/shares")]
    actions = [split("2024-06-10", 10)]

    restated = fundamentals.restate(rows, actions, moment("2025-05-28T20:00:00"))

    assert restated[0]["value"] == pytest.approx(0.598)


def test_a_fact_filed_after_the_split_is_not_adjusted_a_second_time():
    rows = [fact("2024-02-01", "2024-04-28", "0.60", "2025-05-28T12:00:00", "USD/shares")]
    actions = [split("2024-06-10", 10)]

    restated = fundamentals.restate(rows, actions, moment("2026-05-28T20:00:00"))

    assert float(restated[0]["value"]) == pytest.approx(0.60)


def test_a_split_that_has_not_happened_yet_does_not_restate_anything():
    rows = [fact("2024-02-01", "2024-04-28", "5.98", "2024-05-29T12:00:00", "USD/shares")]
    actions = [split("2024-06-10", 10)]

    restated = fundamentals.restate(rows, actions, moment("2024-05-30T20:00:00"))

    assert float(restated[0]["value"]) == pytest.approx(5.98)


def test_revenue_is_never_restated_by_a_split():
    rows = [fact("2024-02-01", "2024-04-28", 1000, "2024-05-29T12:00:00")]
    actions = [split("2024-06-10", 10)]

    restated = fundamentals.restate(rows, actions, moment("2025-05-28T20:00:00"))

    assert restated[0]["value"] == Decimal("1000")


def test_known_at_takes_the_latest_statement_filed_before_the_instant():
    rows = [
        fact("2024-01-01", "2024-03-31", 100, "2024-04-25T12:00:00"),
        fact("2024-01-01", "2024-03-31", 105, "2025-04-25T12:00:00"),
    ]

    early = fundamentals.known_at(rows, moment("2024-06-01T00:00:00"))
    late = fundamentals.known_at(rows, moment("2025-06-01T00:00:00"))

    assert early[date(2024, 3, 31)]["value"] == Decimal("100")
    assert late[date(2024, 3, 31)]["value"] == Decimal("105")


def test_a_fact_filed_at_the_instant_itself_is_not_knowable_before_it():
    """
    A 10-Q accepted in the same second as the release is the release. Letting it
    in would hand the expectation the answer it exists to be measured against.
    """
    rows = [fact("2024-01-01", "2024-03-31", 100, "2024-04-25T12:00:00")]

    assert fundamentals.known_at(rows, moment("2024-04-25T12:00:00")) == {}


def test_the_actual_is_what_was_first_reported_and_not_a_restatement():
    rows = [
        fact("2024-01-01", "2024-03-31", 105, "2025-04-25T12:00:00"),
        fact("2024-01-01", "2024-03-31", 100, "2024-04-25T12:00:00"),
    ]

    assert fundamentals.first_known(rows, date(2024, 3, 31))["value"] == Decimal("100")


def test_the_year_ago_quarter_is_matched_by_date_and_not_by_counting_back():
    """
    A company that skips a filing makes the fourth place back a quarter and a
    half old, and comparing a summer against a spring reads seasonality as
    growth.
    """
    known = {
        date(2023, 3, 31): fact("2023-01-01", "2023-03-31", 100, "2023-04-25T12:00:00"),
        date(2023, 6, 30): fact("2023-04-01", "2023-06-30", 110, "2023-07-25T12:00:00"),
        date(2024, 3, 31): fact("2024-01-01", "2024-03-31", 120, "2024-04-25T12:00:00"),
    }

    found = fundamentals.year_before(known, date(2024, 3, 31))

    assert found["period_end"] == date(2023, 3, 31)


def test_a_quarter_with_no_year_ago_match_returns_nothing():
    known = {
        date(2023, 6, 30): fact("2023-04-01", "2023-06-30", 110, "2023-07-25T12:00:00")
    }

    assert fundamentals.year_before(known, date(2024, 3, 31)) is None


def _growing(quarters: int, start: float = 100.0, rate: float = 1.05) -> dict:
    """
    A company whose every quarter is five percent above the same quarter a year
    before, which is the series the rule should predict exactly.
    """
    known = {}
    base = date(2020, 3, 31)
    for index in range(quarters):
        end = base + pd.DateOffset(months=3 * index)
        known[end.date()] = {
            "period_end": end.date(),
            "value": start * (rate ** (index // 4)),
            "available_at": moment("2020-01-01T00:00:00") + pd.Timedelta(days=index),
            "origin": "reported",
            "unit": "USD",
        }
    return known


def test_the_rule_carries_a_steady_growth_rate_forward():
    known = _growing(9)
    target = sorted(known)[-1]
    history = {end: row for end, row in known.items() if end < target}

    guess = expectation.predict(history, target)

    assert guess["rule"] == "multiplicative"
    assert guess["expected"] == pytest.approx(known[target]["value"], rel=1e-6)


def test_the_rule_turns_additive_when_a_number_goes_negative():
    """
    A ratio across zero is not a rate of change, and an earnings per share
    series crosses zero often enough that this is the ordinary case.
    """
    known = _growing(9)
    ends = sorted(known)
    known[ends[4]]["value"] = -5.0

    target = ends[-1]
    history = {end: row for end, row in known.items() if end < target}

    guess = expectation.predict(history, target)

    assert guess["rule"] == "additive"


def test_no_expectation_without_enough_of_its_own_errors_to_scale_it():
    """
    A surprise is expressed in units of how wrong the rule has been, so a
    company with three quarters of history has no scale and gets no number
    rather than a flattering one.
    """
    known = _growing(9)
    rows = list(known.values())
    for row in rows:
        row["period_start"] = row["period_end"]

    assert expectation.estimate(rows, moment("2030-01-01T00:00:00"), sorted(known)[-1]) is None


def test_the_quarter_a_release_reports_is_the_last_one_to_have_ended():
    ends = [date(2026, 3, 28), date(2026, 6, 27)]

    found = earnings.reported_quarter(ends, moment("2026-07-30T20:30:00"))

    assert found == date(2026, 6, 27)


def test_a_release_too_soon_after_a_quarter_is_not_about_it():
    ends = [date(2026, 6, 27)]

    assert earnings.reported_quarter(ends, moment("2026-06-29T20:30:00")) is None


def test_a_release_a_year_after_a_quarter_is_not_about_it():
    ends = [date(2025, 6, 27)]

    assert earnings.reported_quarter(ends, moment("2026-07-30T20:30:00")) is None


def _series(days: list[str], closes: list[float]) -> dict:
    return {
        "time": np.array([np.datetime64(f"{day}T13:30:00", "ns") for day in days]),
        "open": np.array(closes, float),
        "close": np.array(closes, float),
    }


def test_a_result_after_the_bell_is_measured_against_the_next_session():
    """
    A daily bar is stamped at the instant its session opens, so a release
    accepted at half past four arrives after that day's bar has both opened and
    closed. The session it has yet to move is the next one.
    """
    series = _series(
        ["2026-07-29", "2026-07-30", "2026-07-31"], [338.19, 333.43, 308.91]
    )

    moved = earnings.response(series, moment("2026-07-30T20:30:28"))

    assert moved["session_day"] == date(2026, 7, 31)
    assert moved["prior_close"] == pytest.approx(333.43)
    assert moved["session_pct"] == pytest.approx((308.91 / 333.43 - 1) * 100)


def test_a_result_before_the_open_is_measured_against_the_same_session():
    series = _series(
        ["2026-07-29", "2026-07-30", "2026-07-31"], [338.19, 333.43, 308.91]
    )

    moved = earnings.response(series, moment("2026-07-30T11:00:00"))

    assert moved["session_day"] == date(2026, 7, 30)
    assert moved["prior_close"] == pytest.approx(338.19)


def test_a_release_with_no_session_within_a_week_is_not_measured():
    """
    A wider tolerance would pair the oldest releases with whatever bar the
    series happened to start on, which on a name collected for ten years is a
    price from a different year.
    """
    series = _series(["2026-07-29", "2026-08-20"], [338.19, 333.43])

    assert earnings.response(series, moment("2026-07-30T20:30:00")) is None


def test_a_release_before_the_series_begins_is_not_measured():
    series = _series(["2026-07-29", "2026-07-30"], [338.19, 333.43])

    assert earnings.response(series, moment("2020-01-02T20:30:00")) is None
