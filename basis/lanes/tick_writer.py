import time
from pathlib import Path

import pandas as pd

from basis.lanes.ticks import partition_path

FLUSH_ROWS = 2000
FLUSH_SECONDS = 60


class TickWriter:
    """
    Buffers ticks and writes them as chunk files rather than one file per day.

    Parquet is immutable once written, so a recorder that kept a single file per
    day would have to rewrite the whole day on every flush. Chunks are read back
    identically because the lane globs the directory, and a crash costs at most
    one unflushed buffer instead of the day.
    """

    def __init__(self, root, source: str, symbol: str,
                 flush_rows: int = FLUSH_ROWS, flush_seconds: int = FLUSH_SECONDS):
        self.root = Path(root)
        self.source = source
        self.symbol = symbol
        self.flush_rows = flush_rows
        self.flush_seconds = flush_seconds
        self.buffer: list[dict] = []
        self.last_flush = time.monotonic()
        self.written = 0

    def add(self, tick: dict) -> bool:
        self.buffer.append(tick)
        if len(self.buffer) >= self.flush_rows or self._elapsed():
            return self.flush()
        return False

    def _elapsed(self) -> bool:
        return time.monotonic() - self.last_flush >= self.flush_seconds

    def flush(self) -> bool:
        self.last_flush = time.monotonic()
        if not self.buffer:
            return False

        frame = pd.DataFrame(self.buffer)
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        self.buffer = []

        for day, chunk in frame.groupby(frame["ts"].dt.date):
            target = self._chunk_path(day, chunk["ts"].min())
            target.parent.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(target, index=False, compression="zstd")
            self.written += len(chunk)

        return True

    def _chunk_path(self, day, first_ts) -> Path:
        base = partition_path(self.root, self.source, self.symbol, day)
        stamp = pd.Timestamp(first_ts).strftime("%H%M%S%f")[:-3]
        return base.with_name(f"{day.isoformat()}T{stamp}.parquet")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.flush()
        return False
