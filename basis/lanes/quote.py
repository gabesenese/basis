import json
import time
from datetime import datetime
from pathlib import Path

"""
The record and the display answer different questions, so they get different
files. Parquet is written in two minute batches because a hard kill must not
cost more than two minutes of ticks, which means a screen reading that batch
shows a price up to two minutes old.

This is the other answer: one quote, overwritten in place as it arrives. It is
a display surface and nothing more. No study reads it, nothing here carries an
available_at, and none of it enters the bitemporal record, because a file that
keeps no history cannot answer what was knowable at a past instant.
"""
MIN_INTERVAL_SECONDS = 0.05


class QuoteWriter:
    def __init__(self, path, min_interval: float = MIN_INTERVAL_SECONDS):
        self.path = Path(path)
        self.min_interval = min_interval
        self.last_written = 0.0
        self.written = 0

    def offer(self, tick: dict) -> bool:
        """
        A quote that arrives inside the floor is dropped rather than queued.
        The reader only ever wants the newest one, and a superseded quote held
        back for later would be published as current after it stopped being so.
        """
        now = time.monotonic()
        if self.written and now - self.last_written < self.min_interval:
            return False

        payload = {
            "instrument": tick["instrument"],
            "ts": tick["ts"].isoformat(),
            "bid": float(tick["bid"]),
            "ask": float(tick["ask"]),
            "tradeable": bool(tick.get("tradeable", True)),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_suffix(".tmp")

        try:
            staging.write_text(json.dumps(payload), encoding="utf-8")
            staging.replace(self.path)
        except OSError:
            """
            Windows refuses the replace while a reader holds the target open.
            The next tick writes the same thing a moment later, so losing this
            one costs nothing, and a recorder that died over a display file
            would cost the record.
            """
            return False

        self.last_written = now
        self.written += 1
        return True


def read_quote(path) -> dict | None:
    path = Path(path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    bid, ask = float(payload["bid"]), float(payload["ask"])
    return {
        "instrument": payload["instrument"],
        "ts": datetime.fromisoformat(payload["ts"]),
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "spread_pips": (ask - bid) * 10000,
        "tradeable": payload.get("tradeable", True),
    }
