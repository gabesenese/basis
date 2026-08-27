import io

import pandas as pd

COLUMNS = [
    "instrument_id", "source_id", "granularity", "effective_time",
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close", "tick_count",
]


def ingest(conn, instrument_id: str, source_id: str, granularity: str, frame: pd.DataFrame) -> int:
    """
    Loads through a staging table because a decade of one minute bars is a few
    million rows and row by row inserts would take hours. The table is dropped
    with the transaction, so a failed load leaves nothing behind.

    It is created conditionally and truncated rather than created outright,
    because on commit drop only fires at commit. Two pages loaded inside one
    transaction would otherwise collide on the second call.
    """
    if frame.empty:
        return 0

    staged = frame.rename(columns={"ts": "effective_time"}).copy()
    staged["instrument_id"] = instrument_id
    staged["source_id"] = source_id
    staged["granularity"] = granularity
    staged = staged[COLUMNS]

    conn.execute(
        "create temporary table if not exists staged_bars "
        "(like basis.price_bar) on commit drop"
    )
    conn.execute("truncate staged_bars")

    buffer = io.StringIO()
    staged.to_csv(buffer, index=False, header=False)
    buffer.seek(0)

    with conn.cursor().copy(
        f"copy staged_bars ({', '.join(COLUMNS)}) from stdin with (format csv)"
    ) as copy:
        copy.write(buffer.read())

    result = conn.execute(
        """
        insert into basis.price_bar
        select * from staged_bars
        on conflict (instrument_id, source_id, granularity, effective_time) do nothing
        """
    )
    return result.rowcount
