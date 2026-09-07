from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from basis import accounts
from basis.api.deps import SESSION_KEY, Cached, connection, current_account
from basis.config import settings
from basis.lanes import health as health_lane
from basis.lanes import quote as quote_lane
from basis.lanes import spread_model
from basis.lanes import ticks as tick_lane
from basis.sources import oanda_stream
from basis.study import answer as study_answer

router = APIRouter(prefix="/api")

INSTRUMENT = "EUR_USD"
COST_MARKS = [-300, -60, -5, 1, 5, 15, 40, 90, 300]

_study = Cached(study_answer.assemble)
_profile = Cached(lambda conn: _measure_profile(conn), lease_seconds=3600)


class Credentials(BaseModel):
    email: str
    password: str


class Preferences(BaseModel):
    language: str | None = Field(default=None)
    timezone: str | None = Field(default=None)


def _account_payload(account) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "display_name": account.display_name,
        "language": account.language,
        "timezone": account.timezone,
    }


@router.post("/session")
def sign_in(credentials: Credentials, request: Request, conn=Depends(connection)):
    account = accounts.authenticate(conn, credentials.email, credentials.password)
    conn.commit()

    if account is None:
        raise HTTPException(status_code=401, detail="email or password is wrong")

    request.session[SESSION_KEY] = account.id
    return _account_payload(account)


@router.get("/session")
def read_session(account=Depends(current_account)):
    return _account_payload(account)


@router.delete("/session")
def sign_out(request: Request):
    request.session.clear()
    return {"signed_out": True}


@router.patch("/preferences")
def update_preferences(
    preferences: Preferences, account=Depends(current_account), conn=Depends(connection)
):
    try:
        updated = accounts.set_preferences(
            conn, account.id, preferences.language, preferences.timezone
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    conn.commit()
    return _account_payload(updated)


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _stream_reading() -> dict | None:
    """
    The recorder overwrites the live quote as each tick arrives, while parquet
    only receives them at the two minute flush, so the quote is normally the
    later of the two and the flushed tick is what remains after a restart
    empties it. Taking whichever instant is later needs no rule about which
    file is trustworthy, and a stopped recorder freezes both, which is the
    health card's question rather than this one's.
    """
    readings = [
        quote_lane.read_quote(settings.recorder_quote_path),
        tick_lane.latest_tick(
            settings.basis_parquet_root, oanda_stream.SOURCE_ID, INSTRUMENT
        ),
    ]
    arrived = [reading for reading in readings if reading is not None]
    if not arrived:
        return None

    return max(arrived, key=lambda reading: _utc(reading["ts"]))


def _spot(conn) -> dict | None:
    tick = _stream_reading()
    if tick is not None:
        return {
            "bid": tick["bid"],
            "ask": tick["ask"],
            "mid": (tick["bid"] + tick["ask"]) / 2,
            "spread_pips": tick["spread_pips"],
            "as_of": tick["ts"],
            "source": "oanda stream",
            "measured": True,
        }

    row = conn.execute(
        """
        select effective_time, bid_close, ask_close
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
        order by effective_time desc limit 1
        """,
        (INSTRUMENT,),
    ).fetchone()

    if row is None:
        return None

    bid, ask = float(row["bid_close"]), float(row["ask_close"])
    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "spread_pips": None,
        "as_of": row["effective_time"],
        "source": "oanda M1 bar",
        "measured": True,
    }


def _next_event(conn) -> dict | None:
    row = conn.execute(
        """
        select distinct on (event_key)
               event_key, region, event_code, scheduled_time, available_at, payload
        from basis.calendar_event
        where scheduled_time > now()
        order by event_key, available_at desc
        """,
    ).fetchall()

    upcoming = sorted(row, key=lambda r: r["scheduled_time"])
    if not upcoming:
        return None

    event = upcoming[0]
    return {
        "event_key": event["event_key"],
        "region": event["region"],
        "event_code": event["event_code"],
        "scheduled_time": event["scheduled_time"],
        "known_since": event["available_at"],
        "payload": event["payload"],
    }


def _measure_profile(conn):
    rows = conn.execute(
        """
        select scheduled_time from basis.calendar_event
        where event_code in ('FOMC_DECISION', 'ECB_GOVERNING_COUNCIL')
          and scheduled_time < now()
        order by scheduled_time
        """
    ).fetchall()

    con = tick_lane.connect(settings.basis_parquet_root)
    try:
        return spread_model.measure_profile(
            con, [r["scheduled_time"] for r in rows], "dukascopy", "EURUSD"
        )
    finally:
        con.close()


def _cost_curve(conn, baseline_pips: float | None) -> dict:
    profile = _profile(conn)

    if profile.empty or baseline_pips is None:
        return {"baseline_pips": baseline_pips, "events_measured": 0, "points": []}

    points = []
    for seconds in COST_MARKS:
        estimate = spread_model.estimate(profile, baseline_pips, seconds)
        points.append(
            {
                "seconds": seconds,
                "pips": estimate.pips,
                "provenance": estimate.provenance,
                "basis": estimate.basis,
            }
        )

    return {
        "baseline_pips": baseline_pips,
        "events_measured": int(profile["events"].max()),
        "shape_source": "dukascopy ticks",
        "applied_to": "oanda quiet baseline",
        "points": points,
    }


def _instrument(conn) -> dict:
    """
    The quote currency comes from the instrument row rather than from splitting
    the identifier, because the pair a screen prices in is a property of the
    record and not of how its key happens to be spelled.
    """
    row = conn.execute(
        "select id, base_ccy, quote_ccy, pip_size from basis.instrument where id = %s",
        (INSTRUMENT,),
    ).fetchone()

    if row is None:
        return {"id": INSTRUMENT, "base_ccy": None, "quote_ccy": None, "pip_size": None}

    return {
        "id": row["id"],
        "base_ccy": row["base_ccy"],
        "quote_ccy": row["quote_ccy"],
        "pip_size": float(row["pip_size"]),
    }


@router.get("/today")
def today(account=Depends(current_account), conn=Depends(connection)):
    """
    Spot is read before the clock is stamped. The live quote is overwritten
    while the rest of this answer is assembled, so stamping first would let a
    page dated 11:28:04 carry a price timestamped 11:28:05, which reads as a
    broken clock rather than as the few hundred milliseconds of honest work it
    actually is.
    """
    spot = _spot(conn)
    moment = datetime.now(timezone.utc)
    report = health_lane.inspect(conn, settings.recorder_heartbeat_path, moment)

    quiet_baseline = conn.execute(
        """
        select percentile_cont(0.5) within group (
                 order by (ask_close - bid_close) * 10000
               ) as median_spread
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
          and effective_time > now() - interval '30 days'
        """,
        (INSTRUMENT,),
    ).fetchone()

    baseline = (
        float(quiet_baseline["median_spread"])
        if quiet_baseline and quiet_baseline["median_spread"] is not None
        else None
    )

    return {
        "as_of": moment,
        "market_open": report.open_market,
        "instrument": _instrument(conn),
        "spot": spot,
        "next_event": _next_event(conn),
        "cost": _cost_curve(conn, baseline),
        "health": [
            {
                "subject": f.subject,
                "healthy": f.healthy,
                "detail": f.detail,
                "facts": f.facts,
            }
            for f in report.findings
        ],
    }


@router.get("/calendar")
def calendar(
    account=Depends(current_account),
    conn=Depends(connection),
    months_back: int = Query(default=6, ge=0, le=120),
    months_ahead: int = Query(default=12, ge=0, le=120),
):
    start = datetime.now(timezone.utc) - timedelta(days=30 * months_back)
    finish = datetime.now(timezone.utc) + timedelta(days=30 * months_ahead)

    rows = conn.execute(
        """
        select distinct on (c.event_key)
               c.event_key, c.region, c.event_code, c.scheduled_time,
               c.available_at, c.payload,
               (select count(*) from basis.calendar_event v
                 where v.event_key = c.event_key) as vintages
        from basis.calendar_event c
        where c.scheduled_time between %s and %s
        order by c.event_key, c.available_at desc
        """,
        (start, finish),
    ).fetchall()

    events = sorted(rows, key=lambda r: r["scheduled_time"])
    return {
        "from": start,
        "to": finish,
        "events": [
            {
                "event_key": e["event_key"],
                "region": e["region"],
                "event_code": e["event_code"],
                "scheduled_time": e["scheduled_time"],
                "known_since": e["available_at"],
                "vintages": int(e["vintages"]),
                "payload": e["payload"],
            }
            for e in events
        ],
    }


@router.get("/study/fomc")
def study(account=Depends(current_account), conn=Depends(connection)):
    return _study(conn)


@router.get("/context/positioning")
def positioning(
    account=Depends(current_account),
    conn=Depends(connection),
    weeks: int = Query(default=156, ge=4, le=2000),
):
    rows = conn.execute(
        """
        select effective_time, available_at, metrics
        from basis.positioning
        where contract_code = '099741'
        order by effective_time desc
        limit %s
        """,
        (weeks,),
    ).fetchall()

    series = [
        {
            "effective_time": r["effective_time"],
            "known_since": r["available_at"],
            "noncomm_net": r["metrics"].get("noncomm_net"),
            "noncomm_long": r["metrics"].get("noncomm_positions_long_all"),
            "noncomm_short": r["metrics"].get("noncomm_positions_short_all"),
            "open_interest": r["metrics"].get("open_interest_all"),
        }
        for r in reversed(rows)
    ]

    return {"contract": "EURO FX 099741", "weeks": len(series), "series": series}
