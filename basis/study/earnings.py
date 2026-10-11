from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from basis.lanes import expectation as expectation_lane
from basis.lanes import fundamentals

"""
The earnings gate. Does a company's result, read against what its own history
implied, explain what its shares did next.

It is the same question the FOMC gate asked and it is asked here because the
answer there was that event count is the only source of statistical power left.
Reading one announcement against eight instruments multiplied rows and not
events, so the effective sample stayed at 29 however wide the instrument
universe got. Earnings are the opposite shape: every company reports on its own
calendar against its own history, so two hundred companies are two hundred
independent events a quarter rather than one event seen two hundred ways.

What it cannot claim is that this is the market's expectation. The expectation
here is a naive rule over filings, so the result is a floor. If the floor is
already above zero, a bought consensus is worth pricing. If the floor is flat,
that is a measurement of how much of the move is in the numbers at all.
"""

MEASURES = ["revenue", "eps_diluted"]

"""
How long after a quarter ends a release about it can arrive. Under five days
nobody has closed the books, and past ninety the next quarter has already
ended, so a release outside that window is reporting something other than the
quarter this code would pair it with.
"""
RELEASE_LAG = (5, 90)

"""
A release is not marked against a session more than a long weekend away. A
wider tolerance would pair an event with whatever bar the series happened to
resume on, which on a name collected for ten years means pairing the oldest
releases with a price from a different year.
"""
PRICE_TOLERANCE = timedelta(days=5)

SESSIONS_AHEAD = 5

HORIZONS = ["gap_pct", "session_pct", "five_day_pct"]
GATE_HORIZON = "session_pct"


def releases(conn, ticker: str | None = None) -> list[dict]:
    """
    Every earnings release, read as of its latest statement. An 8-K that is
    amended keeps its event key and gains a row, and the newest one is what
    this reads, exactly as the FOMC side reads a rescheduled meeting.
    """
    clause = "and payload->>'ticker' = %s" if ticker else ""
    rows = conn.execute(
        f"""
        select distinct on (event_key)
               event_key, scheduled_time, payload
        from basis.calendar_event
        where event_code = 'EARNINGS_RELEASE' {clause}
        order by event_key, available_at desc
        """,
        (ticker.upper(),) if ticker else (),
    ).fetchall()

    return sorted(
        (
            {
                "event_key": row["event_key"],
                "accepted_at": row["scheduled_time"],
                "ticker": row["payload"].get("ticker"),
                "cik": row["payload"].get("cik"),
            }
            for row in rows
            if row["payload"].get("ticker") and row["payload"].get("cik")
        ),
        key=lambda row: (row["ticker"], row["accepted_at"]),
    )


def reported_quarter(ends: list[date], accepted_at: datetime) -> date | None:
    """
    The quarter a release is about, which is the most recent one to have ended
    before it. Taking the latest rather than the nearest matters at the edges:
    a company reporting eleven days after its quarter closes is nearer to the
    quarter still running, and that quarter is not what the release says.
    """
    day = accepted_at.date()
    eligible = [
        end for end in ends if RELEASE_LAG[0] <= (day - end).days <= RELEASE_LAG[1]
    ]
    return max(eligible) if eligible else None


def _first_release_per_quarter(rows: list[dict]) -> list[dict]:
    """
    A company that files a preliminary result and then a final one produces two
    releases about one quarter. The first is the news and the second is a
    restatement of it, so only the first is kept.
    """
    kept: dict[tuple, dict] = {}
    for row in rows:
        key = (row["ticker"], row["measure"], row["period_end"])
        current = kept.get(key)
        if current is None or row["accepted_at"] < current["accepted_at"]:
            kept[key] = row
    return sorted(kept.values(), key=lambda row: (row["ticker"], row["accepted_at"]))


def _paired(conn, ticker: str | None = None) -> list[dict]:
    """
    Releases paired with the quarter they report and the number that was
    eventually filed for it. The pairing is what makes an expectation
    addressable: without a period there is nothing to have expected.
    """
    found = []
    cached: dict[tuple[str, str], list[dict]] = {}
    actions: dict[str, list[dict]] = {}

    for release in releases(conn, ticker):
        symbol = release["ticker"]
        if symbol not in actions:
            actions[symbol] = fundamentals.splits(conn, symbol)

        for measure in MEASURES:
            key = (release["cik"], measure)
            if key not in cached:
                cached[key] = fundamentals.series(
                    conn, release["cik"], measure, actions[symbol]
                )
            rows = cached[key]
            if not rows:
                continue

            """
            Every event reads the series in the units that stood at its own
            instant, so the same quarter is restated differently for a release
            before a split and a release after it. That is not an
            inconsistency, it is what the two readers would each have seen.
            """
            stated = fundamentals.restate(
                rows, actions[symbol], release["accepted_at"]
            )

            period_end = reported_quarter(
                sorted({row["period_end"] for row in stated}), release["accepted_at"]
            )
            if period_end is None:
                continue

            actual = fundamentals.first_known(stated, period_end)
            if actual is None:
                continue

            found.append(
                {
                    **release,
                    "measure": measure,
                    "period_end": period_end,
                    "series": stated,
                    "actual": float(actual["value"]),
                    "actual_origin": actual["origin"],
                    "actual_known_at": actual["available_at"],
                }
            )

    return _first_release_per_quarter(found)


def build(conn, ticker: str) -> dict:
    """
    Forms and stores one expectation per release, and hands back what it found
    so the terminal can print the same numbers the study will read.
    """
    written = 0
    skipped = 0
    rows = []

    for pair in _paired(conn, ticker):
        estimate = expectation_lane.estimate(
            pair["series"], pair["accepted_at"], pair["period_end"]
        )
        if estimate is None:
            skipped += 1
            continue

        written += expectation_lane.ingest(
            conn, pair["event_key"], pair["measure"], pair["accepted_at"], estimate
        )
        rows.append(
            {
                "ticker": pair["ticker"],
                "accepted_at": pair["accepted_at"],
                "period_end": pair["period_end"],
                "measure": pair["measure"],
                "expected": estimate["expected"],
                "actual": pair["actual"],
                "surprise": expectation_lane.surprise(pair["actual"], estimate),
                "rule": estimate["rule"],
            }
        )

    return {"rows": rows, "written": written, "skipped": skipped}


def readings(conn, ticker: str) -> list[dict]:
    """
    One company's releases as the screen reads them: what its own history
    implied, what it reported, and the distance between the two in units of how
    wrong that rule has been on this company.

    The expectation is read from the store rather than recomputed, so the
    number on screen is the one the study measured and the one a signal would
    see. The actual is recomputed, because it is not an expectation and does
    not belong in a table whose whole contract is that every row was knowable
    at its own available_at.
    """
    held = {
        (row["event_key"], row["measure"]): row
        for row in stored(conn)
    }

    found = []
    for pair in _paired(conn, ticker):
        estimate = held.get((pair["event_key"], pair["measure"]))
        if estimate is None:
            continue

        payload = estimate["distribution"]
        expected = float(estimate["point_value"])
        scale = float(payload["scale"])

        found.append(
            {
                "event_key": pair["event_key"],
                "measure": pair["measure"],
                "period_end": pair["period_end"],
                "expected": expected,
                "actual": pair["actual"],
                "surprise": (pair["actual"] - expected) / scale,
                "scale": scale,
                "rule": payload["rule"],
                "origin": pair["actual_origin"],
                "residuals": int(payload["residuals"]),
            }
        )

    return found


def _sessions(conn, tickers: list[str]) -> dict[str, dict]:
    rows = conn.execute(
        """
        select instrument_id, effective_time, open, close
        from basis.equity_bar
        where instrument_id = any(%s) and granularity = 'D'
        order by instrument_id, effective_time
        """,
        (tickers,),
    ).fetchall()

    frame = pd.DataFrame(rows)
    if frame.empty:
        return {}

    frame["effective_time"] = pd.to_datetime(
        frame["effective_time"], utc=True
    ).dt.tz_localize(None)

    series = {}
    for ticker, group in frame.groupby("instrument_id"):
        series[ticker] = {
            "time": group["effective_time"].to_numpy(),
            "open": group["open"].to_numpy(float),
            "close": group["close"].to_numpy(float),
        }
    return series


def response(series: dict, accepted_at: datetime) -> dict | None:
    """
    The move a release is answerable for, measured from the last close before
    it to the sessions after it.

    A daily bar is stamped at the instant its session opens, which is what makes
    this a comparison rather than a guess. A result accepted at 16:30 in New
    York arrives after that day's bar has opened and after it has closed, so the
    first bar at or after the acceptance instant is the next session, which is
    the one the news has yet to move. A result accepted before the bell lands on
    the same session, and the same comparison holds without a special case.
    """
    moment = np.datetime64(
        accepted_at.astimezone(timezone.utc).replace(tzinfo=None), "ns"
    )
    place = int(np.searchsorted(series["time"], moment, side="left"))

    if place == 0 or place >= len(series["time"]):
        return None

    if series["time"][place] - moment > np.timedelta64(PRICE_TOLERANCE):
        return None

    before = series["close"][place - 1]
    if before <= 0:
        return None

    later = min(place + SESSIONS_AHEAD - 1, len(series["close"]) - 1)

    return {
        "session_day": pd.Timestamp(series["time"][place]).date(),
        "prior_close": before,
        "session_open": series["open"][place],
        "gap_pct": (series["open"][place] / before - 1) * 100,
        "session_pct": (series["close"][place] / before - 1) * 100,
        "five_day_pct": (series["close"][later] / before - 1) * 100,
        "sessions_ahead": later - place + 1,
    }


def stored(conn) -> list[dict]:
    rows = conn.execute(
        """
        select event_key, measure, effective_time, point_value, distribution
        from basis.expectation
        where source_id = %s
        """,
        (expectation_lane.SOURCE_ID,),
    ).fetchall()
    return [dict(row) for row in rows]


def panel(conn) -> pd.DataFrame:
    """
    One row per release per measure, carrying the standardised surprise and
    what the shares did. Built from the stored expectations rather than from a
    fresh computation, so the study reads the same artifact a signal would.
    """
    held = {(row["event_key"], row["measure"]): row for row in stored(conn)}
    if not held:
        return pd.DataFrame()

    pairs = _paired(conn)
    series = _sessions(conn, sorted({pair["ticker"] for pair in pairs}))

    records = []
    for pair in pairs:
        estimate = held.get((pair["event_key"], pair["measure"]))
        if estimate is None:
            continue

        prices = series.get(pair["ticker"])
        if prices is None:
            continue

        moved = response(prices, pair["accepted_at"])
        if moved is None:
            continue

        payload = estimate["distribution"]
        expected = float(estimate["point_value"])
        scale = float(payload["scale"])

        records.append(
            {
                "event_key": pair["event_key"],
                "ticker": pair["ticker"],
                "accepted_at": pair["accepted_at"],
                "period_end": pair["period_end"],
                "measure": pair["measure"],
                "expected": expected,
                "actual": pair["actual"],
                "actual_origin": pair["actual_origin"],
                "known_before_release": pair["actual_known_at"] < pair["accepted_at"],
                "rule": payload["rule"],
                "scale": scale,
                "residuals": int(payload["residuals"]),
                "z_surprise": (pair["actual"] - expected) / scale,
                **moved,
            }
        )

    return pd.DataFrame(records)


def _fit(frame: pd.DataFrame, response_name: str) -> dict:
    from basis.study import gate

    result = gate.fit(frame, response_name, ["z_surprise"])
    slope = result.slopes[1]

    return {
        "response": response_name,
        "n": int(result.n),
        "r_squared": float(result.r_squared),
        "estimate": float(slope.estimate),
        "robust_low": float(slope.robust_low),
        "robust_high": float(slope.robust_high),
        "boot_low": float(slope.boot_low),
        "boot_high": float(slope.boot_high),
        "p_value": float(slope.p_value),
        "excludes_zero": bool(
            (slope.robust_low > 0 or slope.robust_high < 0)
            and (slope.boot_low > 0 or slope.boot_high < 0)
        ),
    }


def _clustered(frame: pd.DataFrame, response_name: str) -> dict | None:
    """
    The same slope with the errors clustered on the company.

    Thirty companies reporting forty times each are twelve hundred rows and
    nowhere near twelve hundred independent ones. A company that beats its own
    naive rule every quarter contributes forty correlated observations, and an
    interval built as though they were independent would be roughly the honest
    one divided by six. Clustering is what stops the sample size doing work the
    sample cannot.
    """
    import statsmodels.api as sm

    usable = frame[[response_name, "z_surprise", "ticker"]].dropna()
    if usable["ticker"].nunique() < 5:
        return None

    design = sm.add_constant(
        usable[["z_surprise"]].to_numpy(float), has_constant="add"
    )
    model = sm.OLS(usable[response_name].to_numpy(float), design).fit(
        cov_type="cluster",
        cov_kwds={"groups": pd.factorize(usable["ticker"])[0]},
    )
    interval = model.conf_int()

    return {
        "n": int(len(usable)),
        "companies": int(usable["ticker"].nunique()),
        "estimate": float(model.params[1]),
        "cluster_low": float(interval[1][0]),
        "cluster_high": float(interval[1][1]),
        "p_value": float(model.pvalues[1]),
        "r_squared": float(model.rsquared),
        "excludes_zero": bool(interval[1][0] > 0 or interval[1][1] < 0),
    }


def leave_one_company_out(frame: pd.DataFrame, response_name: str) -> dict | None:
    """
    The slope refit with each company held out in turn.

    The FOMC side asks this of single meetings because one afternoon can carry
    an estimate on its own. Here the unit that can carry it is a company: forty
    quarters of one name that happened to beat its own rule while its shares
    rose would produce a slope about that name and not about earnings. A range
    that stays on one side of zero is what says otherwise.
    """
    import statsmodels.api as sm

    usable = frame[[response_name, "z_surprise", "ticker"]].dropna()
    companies = sorted(usable["ticker"].unique())
    if len(companies) < 5:
        return None

    slopes = {}
    for dropped in companies:
        kept = usable[usable["ticker"] != dropped]
        design = sm.add_constant(
            kept[["z_surprise"]].to_numpy(float), has_constant="add"
        )
        model = sm.OLS(kept[response_name].to_numpy(float), design).fit()
        slopes[dropped] = float(model.params[1])

    worst = min(slopes, key=slopes.get)
    best = max(slopes, key=slopes.get)

    return {
        "low": slopes[worst],
        "high": slopes[best],
        "lowest_without": worst,
        "highest_without": best,
        "holds_sign": min(slopes.values()) > 0 or max(slopes.values()) < 0,
    }


def without_derived(frame: pd.DataFrame) -> pd.DataFrame:
    """
    The same panel with every fourth quarter dropped, since those are the ones
    this code worked out rather than read. If the slope lives there it is a
    property of the subtraction rather than of the news.
    """
    return frame[frame["actual_origin"] == "reported"]


def _ordinary_moves(conn, tickers: list[str], event_days: set) -> pd.DataFrame:
    """
    The same close to close move on every session that was not a release, which
    is what says whether an earnings session is a different kind of day or just
    another one.
    """
    series = _sessions(conn, tickers)

    rows = []
    for ticker, prices in series.items():
        closes = prices["close"]
        moves = (closes[1:] / closes[:-1] - 1) * 100
        for place, move in enumerate(moves, start=1):
            day = pd.Timestamp(prices["time"][place]).date()
            if (ticker, day) in event_days:
                continue
            rows.append({"ticker": ticker, "day": day, "move_pct": move})

    return pd.DataFrame(rows)


def assemble(conn) -> dict:
    from basis.study import gate

    frame = panel(conn)
    if frame.empty:
        return {"coverage": {"events": 0, "rows": 0, "companies": 0}, "by_measure": {}}

    tickers = sorted(frame["ticker"].unique())

    """
    A release lands on the session that follows it, and that session is the one
    to hold out of the ordinary comparison. Comparing against every other day
    including the reaction itself would put the event on both sides of the
    ratio and shrink it toward one.
    """
    event_days = set(zip(frame["ticker"], frame["session_day"]))
    ordinary = _ordinary_moves(conn, tickers, event_days)

    by_measure = {}
    for measure in MEASURES:
        subset = frame[frame["measure"] == measure]
        if len(subset) < 10:
            by_measure[measure] = {"events": len(subset), "tested": False}
            continue

        magnitude = subset.assign(
            abs_surprise=subset["z_surprise"].abs(),
            abs_move=subset[GATE_HORIZON].abs(),
        )
        rank_n, rho, rank_p = gate.spearman(magnitude, "abs_surprise", "abs_move")

        """
        A positive surprise should lift the shares, so agreement here is a
        shared sign. The helper counts a flip, which is what a hawkish rate
        surprise does to EUR/USD, so the response is inverted before it is
        passed in and the count means the same thing in both studies.
        """
        by_measure[measure] = {
            "events": len(subset),
            "tested": True,
            "companies": int(subset["ticker"].nunique()),
            "by_horizon": {horizon: _fit(subset, horizon) for horizon in HORIZONS},
            "clustered": {
                horizon: _clustered(subset, horizon) for horizon in HORIZONS
            },
            "leave_one_company_out": {
                horizon: leave_one_company_out(subset, horizon)
                for horizon in HORIZONS
            },
            "reported_only": (
                _clustered(without_derived(subset), GATE_HORIZON)
                if len(without_derived(subset)) >= 10
                else None
            ),
            "sign_agreement": gate.sign_agreement(
                subset.assign(inverted=-subset[GATE_HORIZON]),
                "z_surprise",
                "inverted",
            ),
            "magnitude": {
                "n": int(rank_n),
                "spearman": float(rho),
                "p_value": float(rank_p),
            },
            "derived_actuals": int((subset["actual_origin"] == "derived").sum()),
            "known_before_release": int(subset["known_before_release"].sum()),
        }

    event_median = float(frame[GATE_HORIZON].abs().median())
    ordinary_median = (
        float(ordinary["move_pct"].abs().median()) if not ordinary.empty else None
    )

    return {
        "coverage": {
            "events": int(frame["event_key"].nunique()),
            "rows": len(frame),
            "companies": len(tickers),
            "first": frame["accepted_at"].min().isoformat(),
            "last": frame["accepted_at"].max().isoformat(),
        },
        "gate_horizon": GATE_HORIZON,
        "horizons": HORIZONS,
        "by_measure": by_measure,
        "event_versus_ordinary": {
            "event_n": int(frame["event_key"].nunique()),
            "event_median_pct": event_median,
            "ordinary_n": int(len(ordinary)),
            "ordinary_median_pct": ordinary_median,
            "ratio": event_median / ordinary_median if ordinary_median else None,
        },
    }
