import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx

SOURCE_ID = "fomc"
CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
EASTERN = ZoneInfo("America/New_York")

"""
The statement has been released at 14:00 Eastern since 2013. The page this
parser reads only carries 2021 onward, so a single rule is correct here.
Earlier years live on separate historical pages and released at 14:15, so
extending the backfill past 2021 means revisiting this constant.
"""
STATEMENT_CLOCK = time(14, 0)

_YEAR = re.compile(r'<a id="\d+">(\d{4}) FOMC Meetings</a>')
_ROW = re.compile(
    r'fomc-meeting__month[^>]*>(?:<strong>)?(.*?)(?:</strong>)?</div>\s*'
    r'<div class="fomc-meeting__date[^>]*>(.*?)</div>',
    re.S,
)
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTHS = {name: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTHS.update({name[:3]: i for i, name in enumerate(_MONTH_NAMES, start=1)})


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


def _year_spans(html: str):
    marks = [(m.start(), int(m.group(1))) for m in _YEAR.finditer(html)]
    for index, (start, year) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(html)
        yield year, start, end


def parse(html: str) -> list[dict]:
    meetings = []

    for year, start, end in _year_spans(html):
        for month_text, date_text in _ROW.findall(html[start:end]):
            month_text = " ".join(re.sub(r"<[^>]+>", "", month_text).split())
            date_text = " ".join(re.sub(r"<[^>]+>", "", date_text).split())

            if "notation vote" in date_text.lower():
                continue

            days = re.findall(r"\d{1,2}", date_text)
            if not days:
                continue

            tokens = [t for t in month_text.split("/") if t]
            months = [_MONTHS[t] for t in tokens if t in _MONTHS]
            if len(months) != len(tokens):
                raise ValueError(
                    f"unparsed month in FOMC calendar: {month_text!r} ({date_text!r})"
                )

            first_month = months[0]
            last_month = months[-1]
            last_year = year + 1 if last_month < first_month else year

            decision = date(last_year, last_month, int(days[-1]))
            opens = date(year, first_month, int(days[0]))

            meetings.append(
                {
                    "opens": opens,
                    "decision_date": decision,
                    "statement_time": datetime.combine(
                        decision, STATEMENT_CLOCK, tzinfo=EASTERN
                    ),
                    "projections": "*" in date_text,
                }
            )

    meetings.sort(key=lambda m: m["decision_date"])
    return meetings


def to_calendar_rows(meetings: list[dict], scraped_at=None) -> list[dict]:
    from basis.sources.schedule import available_at

    return [
        {
            "event_key": f"FOMC_{m['decision_date'].isoformat()}",
            "region": "US",
            "event_code": "FOMC_DECISION",
            "scheduled_time": m["statement_time"],
            "available_at": available_at(m["statement_time"], scraped_at),
            "payload": {
                "opens": m["opens"].isoformat(),
                "projections": m["projections"],
            },
        }
        for m in meetings
    ]
