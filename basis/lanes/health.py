import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

"""
The recorder writes its heartbeat on a timer of its own rather than on the
arrival of a tick. A silent weekend and a dead process look identical from the
tick side, and only a clock the process keeps turning tells them apart.
"""
HEARTBEAT_INTERVAL = 15
HEARTBEAT_STALE_AFTER = timedelta(seconds=90)
TICK_STALE_AFTER = timedelta(seconds=120)

WEEK_OPENS_HOUR = 17
WEEK_CLOSES_HOUR = 17


def market_open(moment: datetime) -> bool:
    """
    The spot week runs from Sunday 17:00 Eastern to Friday 17:00 Eastern.
    Holidays that thin the book without closing it are deliberately not
    modelled, because a thin market still quotes and the recorder should still
    be capturing it.
    """
    local = moment.astimezone(EASTERN)
    weekday = local.weekday()

    if weekday == 5:
        return False
    if weekday == 6:
        return local.hour >= WEEK_OPENS_HOUR
    if weekday == 4:
        return local.hour < WEEK_CLOSES_HOUR
    return True


@dataclass
class Heartbeat:
    instrument: str
    started_at: datetime
    updated_at: datetime | None = None
    last_tick_at: datetime | None = None
    ticks_received: int = 0
    ticks_written: int = 0
    reconnects: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "instrument": self.instrument,
                "started_at": self.started_at.isoformat(),
                "updated_at": (self.updated_at or self.started_at).isoformat(),
                "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
                "ticks_received": self.ticks_received,
                "ticks_written": self.ticks_written,
                "reconnects": self.reconnects,
            },
            indent=2,
        )

    def write(self, path: Path) -> None:
        """
        Written beside the target and moved into place, so a reader never finds
        a half written file where it expects the recorder's only status.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc)

        staging = path.with_suffix(".tmp")
        staging.write_text(self.as_json(), encoding="utf-8")
        staging.replace(path)


def read_heartbeat(path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    for key in ("started_at", "updated_at", "last_tick_at"):
        if payload.get(key):
            payload[key] = datetime.fromisoformat(payload[key])
    return payload


@dataclass
class Finding:
    """
    detail is the operator's line in the terminal. facts is the same reading as
    numbers, so a screen can say it in whatever language its reader chose. The
    two must never disagree, which is why facts is derived here rather than
    reconstructed from the sentence.
    """

    subject: str
    healthy: bool
    detail: str
    facts: dict = field(default_factory=dict)


@dataclass
class Report:
    moment: datetime
    open_market: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(finding.healthy for finding in self.findings)


def _age(moment: datetime, since: datetime | None) -> timedelta | None:
    return None if since is None else moment - since


def _seconds(gap: timedelta | None) -> int | None:
    return None if gap is None else int(gap.total_seconds())


def _spell(gap: timedelta | None) -> str:
    if gap is None:
        return "never"
    seconds = int(gap.total_seconds())
    if seconds < 120:
        return f"{seconds}s ago"
    if seconds < 7200:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def inspect(conn, heartbeat_path, moment: datetime | None = None) -> Report:
    moment = moment or datetime.now(timezone.utc)
    report = Report(moment=moment, open_market=market_open(moment))

    beat = read_heartbeat(heartbeat_path)
    if beat is None:
        report.findings.append(
            Finding(
                "recorder",
                False,
                "no heartbeat file, the recorder has never run here",
                {"never_run": True},
            )
        )
    else:
        beat_age = _age(moment, beat["updated_at"])
        alive = beat_age is not None and beat_age <= HEARTBEAT_STALE_AFTER
        report.findings.append(
            Finding(
                "recorder",
                alive,
                f"heartbeat {_spell(beat_age)}, {beat['ticks_written']} ticks written "
                f"since {beat['started_at']:%Y-%m-%d %H:%M} UTC",
                {
                    "age_seconds": _seconds(beat_age),
                    "ticks_written": beat["ticks_written"],
                    "started_at": beat["started_at"],
                    "reconnects": beat.get("reconnects"),
                },
            )
        )

        tick_age = _age(moment, beat["last_tick_at"])
        flowing = tick_age is not None and tick_age <= TICK_STALE_AFTER
        report.findings.append(
            Finding(
                "ticks",
                flowing or not report.open_market,
                f"last tick {_spell(tick_age)}"
                + ("" if report.open_market else ", market closed"),
                {"age_seconds": _seconds(tick_age), "market_closed": not report.open_market},
            )
        )

    row = conn.execute(
        "select max(effective_time) as newest from basis.price_bar"
    ).fetchone()
    newest = row["newest"] if row else None
    bar_age = _age(moment, newest)

    report.findings.append(
        Finding(
            "bars",
            bar_age is not None and bar_age <= timedelta(days=1),
            f"newest M1 bar {_spell(bar_age)}",
            {"age_seconds": _seconds(bar_age), "newest": newest},
        )
    )

    return report
