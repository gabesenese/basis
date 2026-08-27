from psycopg.types.json import Jsonb


def ingest(conn, source_id: str, rows: list[dict]) -> int:
    """
    A rescheduled meeting is recorded as a new vintage rather than an edit.

    The comparison is against the most recent vintage only, not against any
    vintage. Re-scraping an unchanged calendar must not mint rows, and for
    events far enough out that available_at falls back to the scrape instant it
    otherwise would on every run. Comparing against the latest also lets a
    meeting moved away and then moved back register both times.
    """
    written = 0
    for row in rows:
        result = conn.execute(
            """
            insert into basis.calendar_event
              (event_key, source_id, region, event_code, scheduled_time, available_at, payload)
            select %s, %s, %s, %s, %s, %s, %s
            where not exists (
                select 1
                from (
                    select scheduled_time
                    from basis.calendar_event
                    where event_key = %s
                    order by available_at desc
                    limit 1
                ) latest
                where latest.scheduled_time = %s
            )
            """,
            (
                row["event_key"], source_id, row["region"], row["event_code"],
                row["scheduled_time"], row["available_at"], Jsonb(row["payload"]),
                row["event_key"], row["scheduled_time"],
            ),
        )
        written += result.rowcount
    return written
