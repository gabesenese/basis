from datetime import datetime, timedelta, timezone

ANNOUNCEMENT_FLOOR = timedelta(days=180)


def available_at(scheduled_time: datetime, scraped_at: datetime | None = None) -> datetime:
    """
    Central banks publish their meeting calendars a year or more ahead, but the
    scrape only sees today's version of the page, so the true announcement
    instant is not recoverable from it.

    Taking the earlier of the scrape and a floor 180 days before the meeting
    keeps both directions honest. A past meeting is credited to the floor rather
    than to the day we happened to scrape it, which would otherwise make years
    of history look unknowable. A meeting further out than the floor is credited
    to the scrape, since claiming we knew it earlier would be an invention.
    """
    scraped_at = scraped_at or datetime.now(timezone.utc)
    return min(scraped_at, scheduled_time - ANNOUNCEMENT_FLOOR)
