from datetime import timedelta

import pandas as pd

from basis import instruments
from basis.study import fomc, gate

"""
The Phase 2 gate was answered on one instrument and it ran out of sample rather
than out of thesis: 26 meetings carrying 8 target range changes. The same
announcement is read by everything that prices a US rate, so reading it against
eight instruments multiplies the sample on the day it is wired.

Two cautions travel with that, and both are structural rather than cosmetic.

The responses are correlated, so eight instruments on one announcement are not
eight independent readings and the effective sample is smaller than the nominal
one. Every pooled fit here clusters on the event rather than on the row.

And the responses are not comparable in native units. A pip of EUR/USD, a cent
of gold and a tick of a note are different quantities. Each response is
therefore carried three ways: in the instrument's own pips, where the cost is
paid; in basis points of price, which is unit free; and in multiples of that
instrument's own ordinary move over the same window on the same clock, which is
what makes a number large or small for that instrument.
"""

RATE_LEADER = "USB02Y_USD"

"""
The predictor windows. Phase 2 measured the curve repricing from the eve of the
meeting to the close an hour after it, which explained 37 percent of the two
hour move and could not be traded, because the number was not knowable until
after the move it explained had already happened.

A window that opens at the statement and closes a few minutes later is knowable
at the instant it closes. The response is then measured from that same instant
forward, so the predictor and the response never share a second of price. That
is the whole difference between a diagnostic and a signal, and it is why the
contemporaneous version below is kept and marked untradable rather than quietly
dropped.
"""
PREDICTOR_WINDOWS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
}

RESPONSE_END = timedelta(hours=2)

BAR_TOLERANCE = timedelta(minutes=10)

ORDINARY_MOVES_SQL = """
    with days as (
        select generate_series(%s::date, %s::date, interval '1 day')::date as day
    ),
    moments as (
        select day, (day + time '14:00') at time zone 'America/New_York' as opens
        from days
        where extract(isodow from day) between 1 and 5
    )
    select m.day,
      (select (bid_close + ask_close) / 2 from basis.price_bar p
        where p.instrument_id = %s and p.granularity = 'M1'
          and p.effective_time <= m.opens - interval '1 minute'
          and p.effective_time > m.opens - interval '11 minutes'
        order by p.effective_time desc limit 1) as entry,
      (select (bid_close + ask_close) / 2 from basis.price_bar p
        where p.instrument_id = %s and p.granularity = 'M1'
          and p.effective_time <= m.opens + interval '119 minutes'
          and p.effective_time > m.opens + interval '109 minutes'
        order by p.effective_time desc limit 1) as exit
    from moments m
"""


def _mid_at(conn, instrument: str, moment, tolerance: timedelta = BAR_TOLERANCE):
    """
    The same convention Phase 2 fixed: a bar carries the minute that starts at
    its effective_time, so the price at an instant is the close of the bar that
    ends there. Reading the opening bar would put the release inside the price
    called pre release.
    """
    closes_at = moment - timedelta(minutes=1)
    row = conn.execute(
        """
        select (bid_close + ask_close) / 2 as mid
        from basis.price_bar
        where instrument_id = %s and granularity = 'M1'
          and effective_time <= %s and effective_time >= %s
        order by effective_time desc
        limit 1
        """,
        (instrument, closes_at, closes_at - tolerance),
    ).fetchone()
    return float(row["mid"]) if row else None


def _ordinary_moves(conn, instrument: str, start, finish) -> pd.DataFrame:
    rows = conn.execute(
        ORDINARY_MOVES_SQL, (start, finish, instrument, instrument)
    ).fetchall()
    frame = pd.DataFrame(rows).dropna()
    if frame.empty:
        return frame
    entry = frame["entry"].astype(float)
    exit_price = frame["exit"].astype(float)
    frame["move_bps"] = (exit_price / entry - 1.0) * 1e4
    frame["abs_bps"] = frame["move_bps"].abs()
    return frame


def ordinary_sigma(conn, instrument: str, start, finish, exclude: set) -> dict:
    """
    The instrument's own ordinary afternoon, from the same 14:00 Eastern clock
    the announcement uses, over every session in the span that is not a meeting
    day. It is the yardstick every response is divided by, and it is measured
    per instrument because a two hour move that is enormous for a note is
    unremarkable for gold.
    """
    frame = _ordinary_moves(conn, instrument, start, finish)
    if frame.empty:
        return {"n": 0, "sigma_bps": None, "median_abs_bps": None}

    quiet = frame[~frame["day"].isin(exclude)]
    if quiet.empty:
        return {"n": 0, "sigma_bps": None, "median_abs_bps": None}

    return {
        "n": int(len(quiet)),
        "sigma_bps": float(quiet["move_bps"].std(ddof=1)),
        "median_abs_bps": float(quiet["abs_bps"].median()),
    }


def _span(schedule: list[dict]) -> tuple:
    return (
        min(m["scheduled_time"] for m in schedule).date(),
        max(m["scheduled_time"] for m in schedule).date(),
        {m["scheduled_time"].date() for m in schedule},
    )


def panel(conn, universe: list[str] | None = None) -> pd.DataFrame:
    """
    One row per meeting and instrument. The entry is the price at the statement
    and every later reading is taken from the same clock, so a row missing bars
    is dropped rather than filled.
    """
    universe = universe or instruments.ids()
    schedule = fomc.meetings(conn)
    if not schedule:
        return pd.DataFrame()

    span_start, span_end, meeting_days = _span(schedule)

    yardstick = {
        instrument: ordinary_sigma(
            conn, instrument, span_start, span_end, meeting_days
        )
        for instrument in universe
    }

    records = []
    for meeting in schedule:
        at = meeting["scheduled_time"]

        rate_entry = _mid_at(conn, RATE_LEADER, at)
        reprice = {}
        for name, window in PREDICTOR_WINDOWS.items():
            end = _mid_at(conn, RATE_LEADER, at + window)
            reprice[f"reprice_{name}_bps"] = (
                None
                if rate_entry is None or end is None
                else (end / rate_entry - 1.0) * 1e4
            )

        for instrument in universe:
            entry = _mid_at(conn, instrument, at)
            if entry is None:
                continue

            pip = float(instruments.BY_ID[instrument]["pip_size"])
            sigma = yardstick[instrument].get("sigma_bps")
            close = _mid_at(conn, instrument, at + RESPONSE_END)

            record = {
                "event_key": meeting["event_key"],
                "statement_time": at,
                "instrument": instrument,
                "asset_class": instruments.BY_ID[instrument]["asset_class"],
                "entry_mid": entry,
                "sigma_bps": sigma,
                "full_2h_bps": None if close is None else (close / entry - 1.0) * 1e4,
                "full_2h_pips": None if close is None else (close - entry) / pip,
                **reprice,
            }

            for name, window in PREDICTOR_WINDOWS.items():
                opens = _mid_at(conn, instrument, at + window)
                if opens is None or close is None:
                    record[f"after_{name}_bps"] = None
                    record[f"after_{name}_pips"] = None
                    record[f"after_{name}_sigma"] = None
                    continue
                moved = (close / opens - 1.0) * 1e4
                record[f"after_{name}_bps"] = moved
                record[f"after_{name}_pips"] = (close - opens) / pip
                record[f"after_{name}_sigma"] = None if not sigma else moved / sigma

            record["full_2h_sigma"] = (
                None
                if record["full_2h_bps"] is None or not sigma
                else record["full_2h_bps"] / sigma
            )
            records.append(record)

    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    return frame.sort_values(["statement_time", "instrument"]).reset_index(drop=True)


def event_day_lift(conn, universe: list[str] | None = None) -> list[dict]:
    """
    The membership test, run per instrument rather than assumed. An instrument
    earns its place by moving more on meeting afternoons than on ordinary ones
    from the same clock. One that does not is not responding to the event, and
    pooling it in would add rows without adding information.
    """
    from scipy import stats as scipy_stats

    universe = universe or instruments.ids()
    schedule = fomc.meetings(conn)
    if not schedule:
        return []

    span_start, span_end, meeting_days = _span(schedule)

    out = []
    for instrument in universe:
        frame = _ordinary_moves(conn, instrument, span_start, span_end)
        if frame.empty:
            continue

        on = frame[frame["day"].isin(meeting_days)]["abs_bps"]
        off = frame[~frame["day"].isin(meeting_days)]["abs_bps"]
        if len(on) < 5 or len(off) < 30:
            continue

        test = scipy_stats.mannwhitneyu(on, off, alternative="greater")
        out.append(
            {
                "instrument": instrument,
                "asset_class": instruments.BY_ID[instrument]["asset_class"],
                "meetings": int(len(on)),
                "ordinary": int(len(off)),
                "median_meeting_bps": float(on.median()),
                "median_ordinary_bps": float(off.median()),
                "lift": float(on.median() / off.median()) if off.median() else None,
                "p_value": float(test.pvalue),
            }
        )
    return out


def _slope_row(instrument: str, response: str, tradable: bool, result) -> dict:
    slope = result.slopes[1]
    return {
        "instrument": instrument,
        "asset_class": instruments.BY_ID[instrument]["asset_class"],
        "response": response,
        "tradable": tradable,
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


def rate_transmission(frame: pd.DataFrame, window: str = "5m") -> list[dict]:
    """
    The tradable form of the Phase 2 result. The predictor is how the two year
    note repriced between the statement and the end of the window, which is
    knowable the instant that window closes. The response is what the instrument
    then did between that same instant and two hours after the statement, so
    nothing is counted on both sides.

    The untradable form is reported beside it, on the same rows, because the gap
    between the two is the honest measure of how much of the transmission is
    already spent by the time the number can be read.
    """
    predictor = f"reprice_{window}_bps"
    out = []

    for instrument, block in frame.groupby("instrument", sort=False):
        for response, tradable in (
            (f"after_{window}_sigma", True),
            ("full_2h_sigma", False),
        ):
            usable = block[[response, predictor]].dropna()
            if len(usable) < 10:
                continue
            out.append(
                _slope_row(
                    instrument,
                    response,
                    tradable,
                    gate.fit(usable, response, [predictor]),
                )
            )
    return out


def pooled(frame: pd.DataFrame, window: str = "5m") -> dict | None:
    """
    Every instrument except the rate leader itself, in one fit, with standard
    errors clustered on the meeting. Clustering is what stops eight correlated
    readings of one afternoon being counted as eight independent ones. Without
    it the interval here would be roughly a single instrument's divided by the
    square root of eight, which would be a lie.
    """
    import statsmodels.api as sm

    predictor = f"reprice_{window}_bps"
    response = f"after_{window}_sigma"

    usable = frame[frame["instrument"] != RATE_LEADER]
    usable = usable[[response, predictor, "event_key", "instrument"]].dropna()
    if len(usable) < 20:
        return None

    design = sm.add_constant(usable[[predictor]].to_numpy(float), has_constant="add")
    model = sm.OLS(usable[response].to_numpy(float), design).fit(
        cov_type="cluster",
        cov_kwds={"groups": pd.factorize(usable["event_key"])[0]},
    )
    interval = model.conf_int()

    return {
        "n": int(len(usable)),
        "events": int(usable["event_key"].nunique()),
        "instruments": int(usable["instrument"].nunique()),
        "r_squared": float(model.rsquared),
        "estimate": float(model.params[1]),
        "cluster_low": float(interval[1][0]),
        "cluster_high": float(interval[1][1]),
        "p_value": float(model.pvalues[1]),
        "excludes_zero": bool(interval[1][0] > 0 or interval[1][1] < 0),
    }
