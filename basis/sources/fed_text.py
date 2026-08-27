import hashlib
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from pandas.tseries.holiday import USFederalHolidayCalendar

SOURCE_ID = "fomc_text"
EASTERN = ZoneInfo("America/New_York")

STATEMENT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{stamp}a.htm"
MINUTES_URL = "https://www.federalreserve.gov/monetarypolicy/fomcminutes{stamp}.htm"

"""
The statement is public at the moment of the decision, 14:00 Eastern. The
minutes of that same meeting follow three weeks later, also at 14:00.

Three weeks is the Committee's own rule rather than an observation, so a
release that slips a holiday is pushed to the next business day rather than
credited early. Late costs nothing here; early would let a backtest read a
Committee's reasoning before the Committee published it.
"""
RELEASE_CLOCK = time(14, 0)
MINUTES_LAG = timedelta(days=21)

STATEMENT = "statement"
MINUTES = "minutes"

"""
Statements and minutes sit in different containers on the same site, and the
minutes carry an id while the statement is identified only by its grid classes.
Both patterns are tried rather than one loose one, so a layout change fails
with an error instead of quietly capturing the navigation.
"""
_CONTAINERS = [
    re.compile(
        r'<div id="article"[^>]*>(.*?)(?=<div class="col-xs-12 col-sm-4">|<footer)', re.S
    ),
    re.compile(r'<div class="col-xs-12 col-sm-8 col-md-8">(.*?)<div class="row"', re.S),
]
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_MINIMUM_BODY = 400

_holidays = {
    d.date()
    for d in USFederalHolidayCalendar().holidays(start="2000-01-01", end="2035-12-31")
}


def _next_business_day(day: date) -> date:
    while day.weekday() >= 5 or day in _holidays:
        day += timedelta(days=1)
    return day


def published_at(decision_date: date, document_type: str) -> datetime:
    if document_type == STATEMENT:
        return datetime.combine(decision_date, RELEASE_CLOCK, tzinfo=EASTERN)

    released = _next_business_day(decision_date + MINUTES_LAG)
    return datetime.combine(released, RELEASE_CLOCK, tzinfo=EASTERN)


def url_for(decision_date: date, document_type: str) -> str:
    stamp = decision_date.strftime("%Y%m%d")
    template = STATEMENT_URL if document_type == STATEMENT else MINUTES_URL
    return template.format(stamp=stamp)


def fetch(url: str, client: httpx.Client | None = None) -> str | None:
    """
    A missing page is a real answer and not a failure. Older meetings sit on
    different paths and a meeting whose minutes are not due yet has no page at
    all, so a 404 means skip rather than stop.
    """
    owned = client is None
    client = client or httpx.Client(timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    finally:
        if owned:
            client.close()


def parse(html: str) -> str:
    for container in _CONTAINERS:
        match = container.search(html)
        if match is None:
            continue

        text = _SPACE.sub(" ", _TAGS.sub(" ", match.group(1))).strip()
        if len(text) >= _MINIMUM_BODY:
            return text

    raise ValueError("no document body found, the page layout has changed")


def to_document(decision_date: date, document_type: str, body: str) -> dict:
    return {
        "document_key": f"FOMC_{document_type.upper()}_{decision_date.isoformat()}",
        "event_key": f"FOMC_{decision_date.isoformat()}",
        "document_type": document_type,
        "published_at": published_at(decision_date, document_type),
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def collect(decision_dates, client: httpx.Client | None = None) -> tuple[list[dict], list[str]]:
    owned = client is None
    client = client or httpx.Client(timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    documents = []
    missing = []

    try:
        for decision_date in decision_dates:
            for document_type in (STATEMENT, MINUTES):
                url = url_for(decision_date, document_type)
                html = fetch(url, client)
                if html is None:
                    missing.append(url)
                    continue
                documents.append(
                    to_document(decision_date, document_type, parse(html))
                )
    finally:
        if owned:
            client.close()

    return documents, missing


def ingest(conn, documents: list[dict]) -> int:
    """
    A document key is unique, so re-collecting writes nothing. A revision would
    change the hash, and a changed hash on an existing key is a correction the
    Fed made after publishing, which is worth failing loudly on rather than
    silently overwriting.
    """
    written = 0
    for document in documents:
        existing = conn.execute(
            "select body_sha256 from basis.text_document where document_key = %s",
            (document["document_key"],),
        ).fetchone()

        if existing is not None:
            if existing["body_sha256"] != document["body_sha256"]:
                raise ValueError(
                    f"{document['document_key']} changed after publication: "
                    f"{existing['body_sha256'][:12]} became "
                    f"{document['body_sha256'][:12]}"
                )
            continue

        conn.execute(
            """
            insert into basis.text_document
              (document_key, source_id, event_key, document_type, published_at,
               body, body_sha256)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document["document_key"],
                SOURCE_ID,
                document["event_key"],
                document["document_type"],
                document["published_at"],
                document["body"],
                document["body_sha256"],
            ),
        )
        written += 1

    return written
