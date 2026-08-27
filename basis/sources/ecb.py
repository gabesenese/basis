import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

SOURCE_ID = "ecb_calendar"
CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
FRANKFURT = ZoneInfo("Europe/Berlin")

"""
The Governing Council moved its announcement from 13:45 to 14:15 Frankfurt time,
and the press conference from 14:30 to 14:45, starting with the July 2022
meeting. Applying the current clock to older meetings would shift every
pre-2022 event study by half an hour, which at a five minute horizon is the
difference between measuring the reaction and measuring the wrong window.
"""
CLOCK_CHANGE = date(2022, 7, 1)
DECISION_CLOCK = {"before": time(13, 45), "after": time(14, 15)}
PRESSER_CLOCK = {"before": time(14, 30), "after": time(14, 45)}

_PAIR = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)


def fetch_page(client: httpx.Client | None = None) -> str:
    owned = client is None
    client = client or httpx.Client(timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = client.get(CALENDAR_URL)
        response.raise_for_status()
        return response.text
    finally:
        if owned:
            client.close()


def _clean(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def _era(day: date) -> str:
    return "after" if day >= CLOCK_CHANGE else "before"


def parse(html: str) -> list[dict]:
    """
    Two traps live in this page. Non-monetary policy meetings contain the
    monetary policy phrase as a substring, so the negative has to be matched
    first. And the Day 1 marker is not reliable: at least one first day carries
    no marker at all, which would promote it to a decision date.

    The press conference is the dependable signal, because it is what actually
    follows the decision. Selecting on it rather than on the day marker is what
    keeps first days out. Any monetary policy date left without a press
    conference of its own or on the following day is raised rather than dropped,
    since a genuinely missing decision must not pass unnoticed.
    """
    meetings = []
    policy_dates: set[date] = set()

    for raw_date, raw_text in _PAIR.findall(html):
        text = _clean(raw_text)
        lowered = text.lower()

        if "non-monetary policy meeting" in lowered:
            continue
        if "monetary policy meeting" not in lowered:
            continue

        match = re.search(r"(\d{2})/(\d{2})/(\d{4})", _clean(raw_date))
        if not match:
            continue

        day, month, year = (int(g) for g in match.groups())
        meeting_date = date(year, month, day)

        if "followed by press conference" not in lowered:
            policy_dates.add(meeting_date)
            continue

        policy_dates.add(meeting_date)
        decision_date = meeting_date
        era = _era(decision_date)

        meetings.append(
            {
                "decision_date": decision_date,
                "decision_time": datetime.combine(
                    decision_date, DECISION_CLOCK[era], tzinfo=FRANKFURT
                ),
                "presser_time": datetime.combine(
                    decision_date, PRESSER_CLOCK[era], tzinfo=FRANKFURT
                ),
                "two_day": "(day 2)" in lowered,
                "description": text,
            }
        )

    meetings.sort(key=lambda m: m["decision_date"])

    decisions = {m["decision_date"] for m in meetings}
    orphaned = [
        day
        for day in sorted(policy_dates)
        if day not in decisions
        and not any(day + timedelta(days=n) in decisions for n in (1, 2))
    ]
    if orphaned:
        raise ValueError(
            f"ECB monetary policy dates with no press conference nearby: {orphaned}"
        )

    return meetings


def to_calendar_rows(meetings: list[dict], scraped_at=None) -> list[dict]:
    from basis.sources.schedule import available_at

    return [
        {
            "event_key": f"ECB_GC_{m['decision_date'].isoformat()}",
            "region": "EA",
            "event_code": "ECB_GOVERNING_COUNCIL",
            "scheduled_time": m["decision_time"],
            "available_at": available_at(m["decision_time"], scraped_at),
            "payload": {
                "presser_time": m["presser_time"].isoformat(),
                "two_day": m["two_day"],
                "description": m["description"],
            },
        }
        for m in meetings
    ]
