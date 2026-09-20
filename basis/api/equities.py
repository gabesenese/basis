from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from basis import db, instruments
from basis.api.deps import connection, current_account
from basis.sources import edgar, yahoo

router = APIRouter(prefix="/api")

"""
The equity side of the API, and the one honesty problem the FX side does not
have.

There is no real time US equity feed in this project. The chart endpoint behind
this serves a quote that is delayed, and it publishes the instant that quote was
taken. So a price here travels with the moment it was true and the screen
renders its age rather than hiding it. A licensed feed would change that number
and none of the plumbing around it.
"""

"""
The feed publishes a maximum span per interval and answers 422 rather than
truncating when a request exceeds it, so each first pull is asked for a span
comfortably inside the published limit: seven days at one minute, sixty at five
minutes, two years at one hour. The request already reaches a day past now, and
that day counts against the span, which is what the margin is for.
"""
INTERVALS = {
    "M1": {"interval": "1m", "days": 6},
    "M5": {"interval": "5m", "days": 55},
    "H1": {"interval": "1h", "days": 720},
    "D": {"interval": "1d", "days": 3650},
}

"""
How far back a refresh reaches once a name has history. Long enough to close a
weekend or a holiday, short enough that watching a price costs one small
request rather than a decade of it.
"""
TAIL_DAYS = {"M1": 1, "M5": 2, "H1": 5, "D": 5}

"""
How stale a stored series may be before a read refetches it.

This is what makes changing the window feel like changing a window. The bars
for every window a reader has already opened are in Postgres, and answering
from there costs a few milliseconds against the quarter of a second the feed
takes. Paying that upstream round trip again to redraw a series that has not
moved was the whole delay.

A minute chart still refetches on the minute, because there it is the answer
that changed and not the question.
"""
STALE_AFTER = {"M1": 60, "M5": 300, "H1": 1800, "D": 6 * 3600}

"""
When each series was last asked for, which is not the same as how new its
newest bar is, and the difference is the whole bug.

A market that closed on Friday afternoon leaves every stored series looking two
days old all weekend. Measured that way each one is permanently stale, so every
window change refetched a series that could not possibly have changed, and the
staleness bound above bought nothing.

What the bound is really for is not asking the same question twice in a row, so
what it measures is the last time this process asked. Held in memory rather
than in a table because it describes this process's conversation with a feed,
not anything about the market, and losing it on a restart costs one request.
"""
_asked: dict[tuple[str, str], datetime] = {}


def _company(conn, ticker: str) -> dict:
    row = conn.execute(
        "select ticker, cik, name from basis.company where ticker = %s",
        (ticker,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"{ticker} nao esta no indice da SEC"
        )
    return {"ticker": row["ticker"], "cik": row["cik"], "name": row["name"]}


def _newest(conn, ticker: str, granularity: str):
    row = conn.execute(
        """
        select max(effective_time) as newest
        from basis.equity_bar
        where instrument_id = %s and granularity = %s
        """,
        (ticker, granularity),
    ).fetchone()
    return row["newest"] if row else None


def _pull(
    conn, company: dict, granularity: str, moment: datetime, force: bool = False
) -> dict | None:
    """
    The first open of a name pulls its whole history at that granularity, and
    every open after pulls only the tail.

    `force` is what the quote asks for and the bars do not. A price someone is
    watching has to be fetched to be current, so that read always goes
    upstream. A series that has not moved since the last read does not, and
    holding those two to the same rule is what made switching windows wait on
    the network for an answer already in the database.
    """
    spec = INTERVALS[granularity]
    key = (company["ticker"], granularity)
    newest = _newest(conn, company["ticker"], granularity)

    if newest is not None and not force:
        asked = _asked.get(key)
        if asked and (moment - asked).total_seconds() < STALE_AFTER[granularity]:
            return None

    reach = spec["days"] if newest is None else TAIL_DAYS[granularity]
    start = (moment - timedelta(days=reach)).date()

    try:
        with yahoo.open_client() as client:
            result = yahoo.fetch(
                client,
                company["ticker"],
                start,
                (moment + timedelta(days=1)).date(),
                interval=spec["interval"],
            )
    except (httpx.HTTPError, RuntimeError):
        """
        An unofficial endpoint that refuses a request must not empty a screen
        that already holds a series. The stored bars still answer, the quote
        does not, and the caller is told which of the two happened rather than
        being handed a stale price dressed as a live one.
        """
        return None

    _asked[key] = moment
    instruments.register_equity(conn, company["ticker"], company["name"])
    db.upsert_source(conn, yahoo.SOURCE_ID, "price", "Yahoo Finance", False)
    yahoo.ingest_bars(conn, company["ticker"], granularity, yahoo.bars(result))
    if granularity == "D":
        yahoo.ingest_actions(conn, company["ticker"], yahoo.actions(result))
    conn.commit()

    return result.get("meta") or {}


def _previous_close(daily: dict | None, at: datetime | None) -> float | None:
    """
    The reference a change figure is measured against, and it is a session
    rather than a bar.

    Two ways to get this wrong, both of which this exists to prevent. The feed's
    own chartPreviousClose is the close before the whole requested window, so on
    a ten year pull it answers with a price from 2016. And the bar before the
    last one is the previous minute when the reader is looking at a minute
    chart, which turns a day up two percent into a day up one cent.

    So it always reads the daily series, whatever window is on screen: the
    session before the one the quote belongs to, which is the newest stored
    session unless the quote already belongs to that same session.
    """
    if not daily:
        return None
    if at is not None and daily.get("as_of") and daily["as_of"].date() == at.date():
        return daily.get("previous_close")
    return daily.get("close")


def _quote(
    meta: dict | None, moment: datetime, daily: dict | None
) -> dict | None:
    if not meta or meta.get("regularMarketPrice") is None:
        return None

    taken = meta.get("regularMarketTime")
    at = datetime.fromtimestamp(int(taken), timezone.utc) if taken else None

    return {
        "price": float(meta["regularMarketPrice"]),
        "previous_close": _previous_close(daily, at),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "as_of": at,
        "age_seconds": (moment - at).total_seconds() if at else None,
        "market_state": meta.get("marketState"),
        "delayed": True,
        "source": yahoo.SOURCE_ID,
    }


def _bars(conn, ticker: str, granularity: str, count: int) -> list[dict]:
    rows = conn.execute(
        """
        select effective_time, open, high, low, close, volume
        from basis.equity_bar
        where instrument_id = %s and granularity = %s
        order by effective_time desc
        limit %s
        """,
        (ticker, granularity, count),
    ).fetchall()

    return [
        {
            "t": row["effective_time"],
            "o": float(row["open"]),
            "h": float(row["high"]),
            "l": float(row["low"]),
            "c": float(row["close"]),
            "v": int(row["volume"]) if row["volume"] is not None else None,
        }
        for row in reversed(rows)
    ]


def _closes(conn, tickers: list[str]) -> dict[str, dict]:
    """
    The last close and the one before it, for a list of names in a single
    query. A search answering twenty companies must not become twenty round
    trips to colour twenty change figures.
    """
    if not tickers:
        return {}

    rows = conn.execute(
        """
        select instrument_id, effective_time, close, place
        from (
          select instrument_id, effective_time, close,
                 row_number() over (
                   partition by instrument_id order by effective_time desc
                 ) as place
          from basis.equity_bar
          where instrument_id = any(%s) and granularity = 'D'
        ) ranked
        where place <= 2
        """,
        (tickers,),
    ).fetchall()

    seen: dict[str, dict] = {}
    for row in rows:
        entry = seen.setdefault(row["instrument_id"], {})
        if row["place"] == 1:
            entry["close"] = float(row["close"])
            entry["as_of"] = row["effective_time"]
        else:
            entry["previous_close"] = float(row["close"])

    for entry in seen.values():
        previous = entry.get("previous_close")
        if previous:
            entry["change"] = entry["close"] - previous
            entry["change_pct"] = (entry["close"] / previous - 1) * 100

    return seen


def _earnings(conn, ticker: str) -> list[dict]:
    """
    The releases, each carrying what the company's own history implied for the
    quarter it reported.

    Without that, a mark on the chart says only that something was published.
    The gap beside it is a fact and the reader has no way to tell whether it was
    news, which is the difference between a price series with decoration on it
    and a reading.
    """
    from basis.study import earnings

    rows = conn.execute(
        """
        select distinct on (event_key)
               event_key, scheduled_time, available_at, payload
        from basis.calendar_event
        where event_code = 'EARNINGS_RELEASE'
          and payload->>'ticker' = %s
        order by event_key, available_at desc
        """,
        (ticker,),
    ).fetchall()

    against: dict[str, dict] = {}
    for reading in earnings.readings(conn, ticker):
        against.setdefault(reading["event_key"], {})[reading["measure"]] = {
            "expected": reading["expected"],
            "actual": reading["actual"],
            "surprise": reading["surprise"],
            "period_end": reading["period_end"],
            "rule": reading["rule"],
            "origin": reading["origin"],
        }

    return [
        {
            "event_key": row["event_key"],
            "accepted_at": row["scheduled_time"],
            "known_since": row["available_at"],
            "form": row["payload"].get("form"),
            "items": row["payload"].get("items"),
            "accession": row["payload"].get("accession"),
            "against": against.get(row["event_key"]) or None,
        }
        for row in sorted(rows, key=lambda row: row["scheduled_time"])
    ]


def _refresh_later(company: dict, granularity: str) -> None:
    """
    Runs after the response, on its own connection, and takes the staleness
    bound with it: two reads arriving together schedule two refreshes, and the
    second one finds the series already fresh and does nothing.
    """
    with db.connect() as conn:
        _pull(conn, company, granularity, datetime.now(timezone.utc))


def _collect_filings_later(company: dict) -> None:
    """
    Runs after the response has been sent, so it opens its own connection. The
    one the request was served on is closed by then, and reaching for it here
    would fail the moment a company was opened for the first time.
    """
    with db.connect() as conn:
        _collect_filings(conn, company)


def _collect_filings(conn, company: dict) -> None:
    """
    The releases, the reported numbers and the expectations they are read
    against, in one pass behind the response.

    They arrive together because separately they are each useless. An instant
    with no number cannot be measured and a number with no instant cannot be
    placed, and an expectation formed from filings that are not all in yet is
    formed from a history with holes in it.
    """
    from basis.lanes import expectation as expectation_lane
    from basis.study import earnings

    with edgar.open_client() as client:
        payload = edgar.submissions(client, company["cik"])
        history = edgar.all_filings(client, payload)
        facts = edgar.reported(client, company["cik"], earnings.MEASURES)

    releases = edgar.earnings_releases(history)
    if not releases:
        return

    db.upsert_source(conn, edgar.SOURCE_ID, "text", "SEC EDGAR", True)
    edgar.ingest_events(conn, releases)

    acceptance = {row["accession"]: row["accepted_at"] for row in history}
    edgar.ingest_facts(conn, company["cik"], facts, acceptance)
    conn.commit()

    db.upsert_source(
        conn,
        expectation_lane.SOURCE_ID,
        "expectation",
        "Basis",
        False,
        "same quarter a year ago carried forward by the drift of the four since",
    )
    earnings.build(conn, company["ticker"])
    conn.commit()


@router.get("/companies")
def search(
    account=Depends(current_account),
    conn=Depends(connection),
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=12, ge=1, le=50),
):
    """
    Search reads the stored index and never the network, so it answers on a
    keystroke. The close beside a row is only there for names already
    collected: fetching prices for twenty companies nobody has opened would
    spend twenty requests decorating a list.
    """
    found = edgar.find(conn, q, limit)
    closes = _closes(conn, [row["ticker"] for row in found])
    total = conn.execute("select count(*) as n from basis.company").fetchone()

    return {
        "query": q,
        "universe": int(total["n"]),
        "results": [{**row, "last": closes.get(row["ticker"])} for row in found],
    }


@router.get("/companies/collected")
def collected(account=Depends(current_account), conn=Depends(connection)):
    """
    The names this installation holds bars for. It is what an empty search
    offers instead of a suggestion, because a company already collected is a
    real starting point and an editor's pick is not.
    """
    rows = conn.execute(
        """
        select i.id as ticker, i.display_name as name,
               count(b.effective_time) as sessions,
               min(b.effective_time) as oldest,
               max(b.effective_time) as newest
        from basis.instrument i
        join basis.equity_bar b
          on b.instrument_id = i.id and b.granularity = 'D'
        where i.asset_class = 'equity'
        group by i.id, i.display_name
        order by i.id
        """
    ).fetchall()

    closes = _closes(conn, [row["ticker"] for row in rows])

    return {
        "companies": [
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "sessions": int(row["sessions"]),
                "oldest": row["oldest"],
                "newest": row["newest"],
                "last": closes.get(row["ticker"]),
            }
            for row in rows
        ]
    }


"""
The company is read as two things rather than one, and the split is the whole
reason changing a window is quick.

What a reader changes often is the window, and the bars behind it have already
been collected. What has to be current is the price, and it can only be current
by going upstream. Answering both from one route meant every window change paid
a quarter of a second for a quote that had not moved since the last one.

So the header and the quote poll on their own clock, and the series answers
from the database.
"""


@router.get("/company/{ticker}")
def company(
    ticker: str,
    background: BackgroundTasks,
    account=Depends(current_account),
    conn=Depends(connection),
):
    """
    Answers from the store, so opening a company paints at once.

    It blocks on the feed in exactly one case: a company nobody here has opened
    before, where the store has nothing to answer with and waiting is the only
    honest option. Every company already collected is served from Postgres and
    the live quote arrives on its own endpoint a moment later.

    Filings are collected behind the response for the same reason. Reading a
    company's whole submission history from the SEC is the slowest thing on
    this path, it is needed once per company, and nothing on the first paint
    depends on it.
    """
    symbol = ticker.upper()
    found = _company(conn, symbol)
    moment = datetime.now(timezone.utc)

    stored = _closes(conn, [symbol]).get(symbol)
    if stored is None:
        _pull(conn, found, "D", moment, force=True)
        stored = _closes(conn, [symbol]).get(symbol)

    known = _earnings(conn, symbol)
    if not known:
        background.add_task(_collect_filings_later, found)

    return {
        **found,
        "as_of": moment,
        "last_close": stored,
        "earnings": known,
        "collecting": not known,
        "source": yahoo.SOURCE_ID,
    }


@router.get("/company/{ticker}/quote")
def quote(
    ticker: str,
    account=Depends(current_account),
    conn=Depends(connection),
):
    """
    The one read that always goes upstream, because a price is only current if
    it was just asked for. It is on its own route so that being slow costs a
    number arriving a moment late rather than a screen arriving a moment late.
    """
    symbol = ticker.upper()
    found = _company(conn, symbol)
    moment = datetime.now(timezone.utc)

    meta = _pull(conn, found, "D", moment, force=True)
    daily = _closes(conn, [symbol]).get(symbol)

    return {
        "ticker": symbol,
        "as_of": moment,
        "quote": _quote(meta, moment, daily),
        "last_close": daily,
        "feed_answered": meta is not None,
    }


@router.get("/company/{ticker}/bars")
def bars(
    ticker: str,
    background: BackgroundTasks,
    account=Depends(current_account),
    conn=Depends(connection),
    granularity: str = Query(default="D"),
    count: int = Query(default=180, ge=20, le=1200),
):
    """
    A stored series answers immediately and refreshes itself behind the answer.

    Refreshing on the way through was the last place a reader waited on the
    feed. It showed up on the minute chart, whose series goes stale after sixty
    seconds by design: about once a minute, changing to that window cost a round
    trip instead of a database read, and a control that is usually instant and
    occasionally not is worse than one that is honestly slow.

    So the bars on screen are the stored ones, the refresh happens after the
    response, and the next read picks up whatever it brought back. The only
    blocking fetch left is a series this machine has never collected, where
    there is nothing to answer with.
    """
    if granularity not in INTERVALS:
        raise HTTPException(
            status_code=400, detail=f"granularidade {granularity} nao existe"
        )

    symbol = ticker.upper()
    found = _company(conn, symbol)
    moment = datetime.now(timezone.utc)

    key = (symbol, granularity)
    held = _newest(conn, symbol, granularity) is not None
    asked = _asked.get(key)
    due = asked is None or (moment - asked).total_seconds() >= STALE_AFTER[granularity]

    if not held:
        _pull(conn, found, granularity, moment)
    elif due:
        background.add_task(_refresh_later, found, granularity)

    return {
        "ticker": symbol,
        "as_of": moment,
        "granularity": granularity,
        "bars": _bars(conn, symbol, granularity, count),
        "collected": not held,
        "refreshing": held and due,
        "source": yahoo.SOURCE_ID,
    }


@router.delete("/company/{ticker}/collected")
def forget(
    ticker: str,
    account=Depends(current_account),
    conn=Depends(connection),
):
    """
    Forgets a company: its bars, its corporate actions, its filings and the
    instrument row itself. What survives is its line in the SEC index, because
    that is the searchable universe rather than anything collected, and a
    company can be opened again the moment it is wanted.

    It refuses anything that is not an equity, and that guard is the reason it
    is safe to expose at all. The same tables hold the reference instruments,
    and EUR_USD alone carries the entire FOMC study: a mistyped ticker must not
    be able to delete a measurement that took a week to collect.
    """
    symbol = ticker.upper()

    row = conn.execute(
        "select id, asset_class, display_name from basis.instrument where id = %s",
        (symbol,),
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"{symbol} nao esta coletada")

    if row["asset_class"] != "equity":
        raise HTTPException(
            status_code=409,
            detail=f"{symbol} e um instrumento de referencia, nao uma empresa coletada",
        )

    bars = conn.execute(
        "delete from basis.equity_bar where instrument_id = %s", (symbol,)
    ).rowcount
    actions = conn.execute(
        "delete from basis.corporate_action where instrument_id = %s", (symbol,)
    ).rowcount
    documents = conn.execute(
        "delete from basis.text_document where event_key like %s",
        (f"EARN:{symbol}:%",),
    ).rowcount
    expectations = conn.execute(
        "delete from basis.expectation where event_key like %s",
        (f"EARN:{symbol}:%",),
    ).rowcount
    events = conn.execute(
        """
        delete from basis.calendar_event
        where event_code = 'EARNINGS_RELEASE' and payload->>'ticker' = %s
        """,
        (symbol,),
    ).rowcount

    """
    The reported facts go with the rest, and they are found through the SEC
    index rather than through the instrument row, because they are keyed by CIK
    and a company keeps that when it changes ticker.
    """
    facts = conn.execute(
        """
        delete from basis.company_fact
        where cik in (select cik from basis.company where ticker = %s)
        """,
        (symbol,),
    ).rowcount

    conn.execute("delete from basis.instrument where id = %s", (symbol,))
    conn.commit()

    for granularity in INTERVALS:
        _asked.pop((symbol, granularity), None)

    return {
        "ticker": symbol,
        "name": row["display_name"],
        "removed": {
            "bars": bars,
            "actions": actions,
            "documents": documents,
            "earnings": events,
            "expectations": expectations,
            "facts": facts,
        },
    }
