from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd


def partition_path(root: Path, source: str, symbol: str, day) -> Path:
    return (
        Path(root)
        / f"source={source}"
        / f"symbol={symbol}"
        / f"year={day.year:04d}"
        / f"{day.isoformat()}.parquet"
    )


def chunk_paths(root: Path, source: str, symbol: str, day) -> list[Path]:
    canonical = partition_path(root, source, symbol, day)
    return sorted(canonical.parent.glob(f"{day.isoformat()}T*.parquet"))


def compact_day(root: Path, source: str, symbol: str, day) -> int:
    """
    Folds a closed day's flush chunks into the one file the partition is named
    for. A recorder flushing on a timer writes hundreds of files a day, and the
    lane reads the whole tree through a glob, so left alone the read cost grows
    with uptime rather than with data.

    The canonical file joins its own inputs when it already exists, so running
    this twice is a merge and not a truncation. Chunks are removed only after
    the merged file is on disk.
    """
    chunks = chunk_paths(root, source, symbol, day)
    if not chunks:
        return 0

    canonical = partition_path(root, source, symbol, day)
    sources = ([canonical] if canonical.exists() else []) + chunks

    frame = pd.concat([pd.read_parquet(path) for path in sources], ignore_index=True)
    frame = frame.sort_values("ts").drop_duplicates().reset_index(drop=True)

    staging = canonical.with_suffix(".compacting")
    frame.to_parquet(staging, index=False, compression="zstd")
    staging.replace(canonical)

    for chunk in chunks:
        chunk.unlink()

    return len(frame)


def recorded_days(root: Path, source: str, symbol: str) -> list:
    from datetime import date

    base = Path(root) / f"source={source}" / f"symbol={symbol}"
    if not base.exists():
        return []

    days = set()
    for path in base.glob("year=*/*.parquet"):
        try:
            days.add(date.fromisoformat(path.stem.split("T")[0]))
        except ValueError:
            continue
    return sorted(days)


def latest_tick(root: Path, source: str, symbol: str) -> dict | None:
    """
    Reads the newest file in the partition rather than opening the whole tree.
    A live quote is wanted on every page view, and globbing several months of
    parquet to answer what the last tick was would make the cheapest question
    on the page the most expensive one.
    """
    base = Path(root) / f"source={source}" / f"symbol={symbol}"
    if not base.exists():
        return None

    files = sorted(base.glob("year=*/*.parquet"), key=lambda p: (p.stem, p.stat().st_mtime))
    if not files:
        return None

    frame = pd.read_parquet(files[-1])
    if frame.empty:
        return None

    row = frame.sort_values("ts").iloc[-1]
    return {
        "ts": pd.Timestamp(row["ts"]).to_pydatetime(),
        "bid": float(row["bid"]),
        "ask": float(row["ask"]),
        "spread_pips": (float(row["ask"]) - float(row["bid"])) * 10000,
    }


def connect(root: Path) -> duckdb.DuckDBPyConnection:
    """
    Ticks from different venues sit in the same view but stay distinguishable,
    because a Dukascopy spread and an OANDA spread are different products and
    averaging them would be meaningless.

    The session is pinned to UTC. DuckDB otherwise renders timestamps in the
    machine's local zone, which is correct as an instant but reads as a
    different wall clock than every other surface in this project.
    """
    con = duckdb.connect()
    con.execute("set timezone = 'UTC'")
    glob = str(Path(root) / "source=*" / "symbol=*" / "year=*" / "*.parquet").replace("\\", "/")
    con.execute(
        f"""
        create view ticks as
        select *,
               regexp_extract(filename, 'source=([a-z_]+)', 1) as source,
               regexp_extract(filename, 'symbol=([A-Z_]+)', 1) as symbol
        from read_parquet('{glob}', filename = true, union_by_name = true)
        """
    )
    return con


def spot_as_of(con, symbol: str, moment: datetime) -> dict | None:
    row = con.execute(
        """
        select ts, bid, ask, (ask - bid) * 10000 as spread_pips
        from ticks
        where symbol = ? and ts <= ?
        order by ts desc
        limit 1
        """,
        [symbol, moment],
    ).fetchone()

    if row is None:
        return None
    return {"ts": row[0], "bid": row[1], "ask": row[2], "spread_pips": row[3]}


def bars(con, symbol: str, start: datetime, end: datetime, seconds: int) -> pd.DataFrame:
    return con.execute(
        """
        select
            time_bucket(interval (?) second, ts) as bucket,
            first(bid order by ts) as bid_open,
            max(bid) as bid_high,
            min(bid) as bid_low,
            last(bid order by ts) as bid_close,
            first(ask order by ts) as ask_open,
            max(ask) as ask_high,
            min(ask) as ask_low,
            last(ask order by ts) as ask_close,
            count(*) as tick_count
        from ticks
        where symbol = ? and ts >= ? and ts < ?
        group by bucket
        order by bucket
        """,
        [seconds, symbol, start, end],
    ).df()


def spread_profile(con, symbol: str, start: datetime, end: datetime, seconds: int) -> pd.DataFrame:
    """
    Spread by time bucket around an event. This is what calibrates the dead
    window and the cost hurdle: the entry price is worthless if the spread at
    that instant eats the expected move.
    """
    return con.execute(
        """
        select
            time_bucket(interval (?) second, ts) as bucket,
            median((ask - bid) * 10000) as median_pips,
            quantile_cont((ask - bid) * 10000, 0.95) as p95_pips,
            max((ask - bid) * 10000) as max_pips,
            count(*) as tick_count
        from ticks
        where symbol = ? and ts >= ? and ts < ?
        group by bucket
        order by bucket
        """,
        [seconds, symbol, start, end],
    ).df()


def gaps(con, symbol: str, start: datetime, end: datetime, threshold_seconds: int) -> pd.DataFrame:
    return con.execute(
        """
        with spaced as (
            select ts, lag(ts) over (order by ts) as previous
            from ticks
            where symbol = ? and ts >= ? and ts < ?
        )
        select previous as gap_start, ts as gap_end,
               epoch(ts - previous) as gap_seconds
        from spaced
        where previous is not null and ts - previous > interval (?) second
        order by gap_seconds desc
        """,
        [symbol, start, end, threshold_seconds],
    ).df()
