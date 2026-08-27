from datetime import datetime, timedelta

import pandas as pd

from basis.lanes.ticks import partition_path
from basis.sources import dukascopy as dk


def hours_covering(event: datetime, before: timedelta, after: timedelta):
    start = (event - before).replace(minute=0, second=0, microsecond=0)
    finish = event + after
    cursor = start
    while cursor <= finish:
        yield cursor
        cursor += timedelta(hours=1)


def fetch_window(client, event: datetime, symbol: str,
                 before: timedelta, after: timedelta) -> pd.DataFrame:
    frames = [dk.fetch_hour(client, symbol, hour)
              for hour in hours_covering(event, before, after)]
    populated = [f for f in frames if not f.empty]
    if not populated:
        return dk._empty_frame()
    return pd.concat(populated, ignore_index=True)


def backfill_events(root, symbol: str, events: list[datetime],
                    before=timedelta(hours=1), after=timedelta(hours=2),
                    overwrite: bool = False):
    """
    Pulls only the hours that straddle each event rather than a continuous
    history. A decade of ticks is 87,600 files and the feed will not tolerate
    it; a hundred events at three hours each is a few hundred, and it covers
    the only windows where tick resolution changes an answer.

    Returns what was written and what was deferred. A throttled event is
    deferred rather than fatal, so one refusal costs that event and not the
    whole run, and the caller learns which windows are still missing instead of
    inferring completeness from a run that exited cleanly.
    """
    written = []
    deferred = []

    with dk.open_client() as client:
        for event in events:
            day = event.date()
            target = partition_path(root, dk.SOURCE_ID, symbol, day)
            if target.exists() and not overwrite:
                continue

            try:
                frame = fetch_window(client, event, symbol, before, after)
            except dk.FeedThrottled as exc:
                deferred.append((event, str(exc)))
                continue

            if frame.empty:
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, index=False, compression="zstd")
            written.append((event, len(frame)))

    return written, deferred
