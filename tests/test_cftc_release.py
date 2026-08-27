from datetime import date, timedelta

import pytest

from basis.sources import cftc


def as_local(report_date):
    return cftc.release_time(report_date).strftime("%Y-%m-%d %H:%M %Z")


def test_ordinary_week_releases_the_following_friday():
    assert as_local(date(2026, 8, 18)) == "2026-08-21 15:30 EDT"


def test_holiday_on_the_release_day_pushes_to_monday():
    assert as_local(date(2025, 7, 1)) == "2025-07-07 15:30 EDT"


def test_thanksgiving_pushes_to_monday():
    assert as_local(date(2025, 11, 25)) == "2025-12-01 15:30 EST"


def test_monday_holiday_inside_the_report_week_still_delays():
    assert as_local(date(2025, 9, 2)) == "2025-09-08 15:30 EDT"


def test_christmas_and_new_year_stack():
    release = cftc.release_time(date(2025, 12, 30))
    assert release.date() > date(2026, 1, 2)


@pytest.mark.parametrize("weeks", range(260))
def test_release_is_always_a_weekday_after_the_report(weeks):
    report_date = date(2021, 1, 5) + timedelta(weeks=weeks)
    release = cftc.release_time(report_date)

    assert release.date() > report_date
    assert release.weekday() < 5
    assert release.date() not in cftc._holidays
    assert release.strftime("%H:%M") == "15:30"


@pytest.mark.parametrize("weeks", range(260))
def test_available_at_never_precedes_effective_time(weeks):
    report_date = date(2021, 1, 5) + timedelta(weeks=weeks)
    rows = cftc.to_rows(
        [{"report_date_as_yyyy_mm_dd": report_date.isoformat(), "open_interest_all": "1"}]
    )
    assert rows[0]["available_at"] > rows[0]["effective_time"]
