import logging
import logging.handlers
import signal
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from basis.lanes import ticks as tick_lane
from basis.lanes.health import HEARTBEAT_INTERVAL, Heartbeat
from basis.lanes.quote import QuoteWriter
from basis.lanes.tick_writer import TickWriter
from basis.sources import oanda_stream

LOG_BYTES = 5_000_000
LOG_BACKUPS = 5

"""
Two minutes of buffered ticks is what a hard kill costs, and Windows ends a
scheduled task by terminating the process rather than by asking it to stop.
Shorter flushes would cut that loss and multiply the file count the compactor
then has to fold back together.
"""
SERVICE_FLUSH_SECONDS = 120


def build_logger(log_path: Path) -> logging.Logger:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("basis.recorder")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    return logger


class Recorder:
    def __init__(
        self,
        root,
        instrument: str,
        heartbeat_path,
        log_path,
        quote_path=None,
        flush_seconds: int = SERVICE_FLUSH_SECONDS,
    ):
        self.root = Path(root)
        self.instrument = instrument
        self.heartbeat_path = Path(heartbeat_path)
        self.quote_path = Path(quote_path) if quote_path else None
        self.flush_seconds = flush_seconds
        self.log = build_logger(log_path)
        self.stopping = threading.Event()
        self.heartbeat = Heartbeat(
            instrument=instrument, started_at=datetime.now(timezone.utc)
        )

    def _install_signals(self) -> None:
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            received = getattr(signal, name, None)
            if received is None:
                continue
            try:
                signal.signal(received, lambda *_: self.stopping.set())
            except (ValueError, OSError):
                continue

    def _beat(self) -> None:
        while not self.stopping.wait(HEARTBEAT_INTERVAL):
            self.heartbeat.write(self.heartbeat_path)

    def compact_closed_days(self) -> None:
        """
        Yesterday and earlier only. Today is still being written to, and folding
        a day while the writer holds it open would race the flush that follows.
        """
        today = datetime.now(timezone.utc).date()
        for day in tick_lane.recorded_days(
            self.root, oanda_stream.SOURCE_ID, self.instrument
        ):
            if day >= today:
                continue
            if not tick_lane.chunk_paths(
                self.root, oanda_stream.SOURCE_ID, self.instrument, day
            ):
                continue

            rows = tick_lane.compact_day(
                self.root, oanda_stream.SOURCE_ID, self.instrument, day
            )
            self.log.info("compacted %s into %d ticks", day.isoformat(), rows)

    def run(self, stop=None) -> int:
        self._install_signals()
        self.compact_closed_days()

        beating = threading.Thread(target=self._beat, daemon=True)
        beating.start()

        self.heartbeat.write(self.heartbeat_path)
        self.log.info("recording %s into %s", self.instrument, self.root)

        def should_stop() -> bool:
            return self.stopping.is_set() or (stop is not None and stop())

        def on_reconnect(reason: str, delay: int) -> None:
            self.heartbeat.reconnects += 1
            self.log.warning("reconnecting in %ss after %s", delay, reason)

        writer = TickWriter(
            self.root,
            oanda_stream.SOURCE_ID,
            self.instrument,
            flush_seconds=self.flush_seconds,
        )
        quote = QuoteWriter(self.quote_path) if self.quote_path else None
        rolled = date.min

        try:
            with writer:
                for tick in oanda_stream.stream(
                    [self.instrument], stop=should_stop, on_reconnect=on_reconnect
                ):
                    writer.add(tick)
                    if quote is not None:
                        quote.offer(tick)
                    self.heartbeat.ticks_received += 1
                    self.heartbeat.ticks_written = writer.written
                    self.heartbeat.last_tick_at = tick["ts"]

                    today = tick["ts"].date()
                    if today > rolled:
                        if rolled > date.min:
                            writer.flush()
                            self.compact_closed_days()
                        rolled = today
        except KeyboardInterrupt:
            self.log.info("interrupted")
        finally:
            self.stopping.set()
            self.heartbeat.ticks_written = writer.written
            self.heartbeat.write(self.heartbeat_path)
            self.log.info(
                "stopped after %d ticks received, %d written, %d reconnects",
                self.heartbeat.ticks_received,
                writer.written,
                self.heartbeat.reconnects,
            )

        return writer.written
