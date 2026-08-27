from datetime import date, datetime, timezone

import pytest

from basis.sources import ecb, fomc
from basis.sources.schedule import available_at


def fomc_page(rows: str) -> str:
    return f'<a id="1">2024 FOMC Meetings</a>{rows}'


def fomc_row(month: str, day: str) -> str:
    return (
        f'<div class="fomc-meeting__month col-xs-5"><strong>{month}</strong></div>'
        f'<div class="fomc-meeting__date col-lg-1">{day}</div>'
    )


def test_fomc_two_day_meeting_decides_on_the_second_day():
    meeting = fomc.parse(fomc_page(fomc_row("January", "30-31")))[0]
    assert meeting["opens"] == date(2024, 1, 30)
    assert meeting["decision_date"] == date(2024, 1, 31)


def test_fomc_meeting_spanning_two_months_uses_the_later_month():
    meeting = fomc.parse(fomc_page(fomc_row("Apr/May", "30-1")))[0]
    assert meeting["opens"] == date(2024, 4, 30)
    assert meeting["decision_date"] == date(2024, 5, 1)


def test_fomc_meeting_spanning_the_year_end_rolls_the_year():
    meeting = fomc.parse(fomc_page(fomc_row("Dec/Jan", "31-1")))[0]
    assert meeting["opens"] == date(2024, 12, 31)
    assert meeting["decision_date"] == date(2025, 1, 1)


def test_fomc_notation_vote_is_not_a_meeting():
    assert fomc.parse(fomc_page(fomc_row("August", "22 (notation vote)"))) == []


def test_fomc_projection_marker_is_carried():
    assert fomc.parse(fomc_page(fomc_row("March", "19-20*")))[0]["projections"] is True


def test_fomc_unknown_month_raises_instead_of_dropping_the_meeting():
    with pytest.raises(ValueError, match="unparsed month"):
        fomc.parse(fomc_page(fomc_row("Smarch", "19-20")))


def test_fomc_statement_time_follows_daylight_saving():
    winter = fomc.parse(fomc_page(fomc_row("January", "30-31")))[0]
    summer = fomc.parse(fomc_page(fomc_row("June", "11-12")))[0]

    assert winter["statement_time"].astimezone(timezone.utc).hour == 19
    assert summer["statement_time"].astimezone(timezone.utc).hour == 18


def ecb_page(entries: list[tuple[str, str]]) -> str:
    return "".join(f"<dt>{d}</dt><dd>{t}</dd>" for d, t in entries)


DECISION = "Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference"
DAY_ONE = "Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 1)"
GOVERNANCE = "Governing Council of the ECB: non-monetary policy meeting (virtual)"


def test_ecb_non_monetary_meeting_is_excluded_despite_the_substring():
    assert ecb.parse(ecb_page([("30/09/2026", GOVERNANCE)])) == []


def test_ecb_first_day_is_excluded():
    found = ecb.parse(ecb_page([("28/10/2026", DAY_ONE), ("29/10/2026", DECISION)]))
    assert [m["decision_date"] for m in found] == [date(2026, 10, 29)]


def test_ecb_first_day_missing_its_marker_is_still_excluded():
    unmarked = "Governing Council of the ECB: monetary policy meeting in Frankfurt"
    found = ecb.parse(ecb_page([("11/10/2028", unmarked), ("12/10/2028", DECISION)]))
    assert [m["decision_date"] for m in found] == [date(2028, 10, 12)]


def test_ecb_policy_date_with_no_press_conference_nearby_raises():
    unmarked = "Governing Council of the ECB: monetary policy meeting in Frankfurt"
    with pytest.raises(ValueError, match="no press conference"):
        ecb.parse(ecb_page([("11/03/2027", unmarked)]))


def test_ecb_clock_moved_with_the_july_2022_meeting():
    before = ecb.parse(ecb_page([("09/06/2022", DECISION)]))[0]
    after = ecb.parse(ecb_page([("21/07/2022", DECISION)]))[0]

    assert before["decision_time"].strftime("%H:%M") == "13:45"
    assert before["presser_time"].strftime("%H:%M") == "14:30"
    assert after["decision_time"].strftime("%H:%M") == "14:15"
    assert after["presser_time"].strftime("%H:%M") == "14:45"


def test_ecb_decision_converts_to_the_expected_utc_instant():
    summer = ecb.parse(ecb_page([("10/09/2026", DECISION)]))[0]
    winter = ecb.parse(ecb_page([("29/10/2026", DECISION)]))[0]

    assert summer["decision_time"].astimezone(timezone.utc).strftime("%H:%M") == "12:15"
    assert winter["decision_time"].astimezone(timezone.utc).strftime("%H:%M") == "13:15"


NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def test_past_event_is_credited_to_the_floor_not_to_the_scrape():
    scheduled = datetime(2024, 3, 20, 18, tzinfo=timezone.utc)
    assert available_at(scheduled, NOW) == datetime(2023, 9, 22, 18, tzinfo=timezone.utc)


def test_distant_future_event_is_credited_to_the_scrape():
    scheduled = datetime(2027, 12, 8, 19, tzinfo=timezone.utc)
    assert available_at(scheduled, NOW) == NOW


def test_available_at_is_never_after_the_event():
    for months in range(1, 40):
        scheduled = datetime(2026, 8, 25, 12, tzinfo=timezone.utc).replace(
            year=2026 + months // 12, month=(months % 12) + 1
        )
        assert available_at(scheduled, NOW) < scheduled
