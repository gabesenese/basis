from datetime import date, datetime

"""
The quarterly series a company actually reported, rebuilt from XBRL durations.

XBRL does not publish a quarter, it publishes periods, and which periods exist
depends on the filing. A 10-Q states its own quarter and the year to date. A
10-K states the full year and never the fourth quarter, because no quarterly
report covers it. Reading only the ninety day durations therefore silently
drops one release in four, and the one it drops is the annual, which is the
release a company says the most at.

So the fourth quarter is derived, as the year minus the nine months already
reported, and it is marked as derived rather than passed off as something the
company printed.
"""

QUARTER = (80, 100)
NINE_MONTHS = (260, 285)
YEAR = (350, 380)

YEAR_BEFORE = (340, 390)


"""
A per share number is denominated in a share count, and a split changes the
share count without changing anything about the company.

Prices already survive this, because the feed restates the whole series into
the units set by the most recent split and a return is invariant under that.
An earnings per share series does not survive it, because XBRL states each fact
in the units in force when it was filed. NVIDIA's quarter to April 2024 was
filed at 5.98 a share and restated at 0.60 after the ten for one split in June,
and both rows are in the store. Reading the first against a later quarter
compares a number to a tenth of itself and calls the difference a surprise.

So a fact's units are set by its filing date, and expressing it at a later
instant means dividing by every split that took effect between the two. A row
already filed after the split is divided by nothing and agrees with the
restated one, which is the check that the rule is right rather than merely
consistent.
"""
PER_SHARE = "/shares"


def splits(conn, ticker: str) -> list[dict]:
    rows = conn.execute(
        """
        select effective_date, numerator, denominator, available_at
        from basis.corporate_action
        where instrument_id = %s and action_type = 'split'
        order by effective_date
        """,
        (ticker.upper(),),
    ).fetchall()
    return [dict(row) for row in rows]


def split_factor(rows: list[dict], filed: date, moment: datetime) -> float:
    """
    The cumulative ratio between the units a fact was filed in and the units in
    force at an instant. A split effective on the filing day itself counts as
    already applied, since a report published that day states the new count.
    """
    factor = 1.0
    for row in rows:
        if row["effective_date"] <= filed or row["available_at"] > moment:
            continue
        factor *= float(row["numerator"]) / float(row["denominator"])
    return factor


def restate(rows: list[dict], actions: list[dict], moment: datetime) -> list[dict]:
    """
    The series expressed in the units in force at `moment`, which is the only
    form in which two quarters filed either side of a split can be compared.
    Measures that are not per share pass through untouched, because a dollar of
    revenue is a dollar however many shares it is divided among.
    """
    if not actions:
        return rows

    restated = []
    for row in rows:
        if PER_SHARE not in row["unit"]:
            restated.append(row)
            continue

        factor = split_factor(actions, row["available_at"].date(), moment)
        restated.append(
            {**row, "value": float(row["value"]) / factor} if factor != 1.0 else row
        )
    return restated


def _within(span, bounds) -> bool:
    return span is not None and bounds[0] <= span <= bounds[1]


def _rows(conn, cik: str, measure: str) -> list[dict]:
    """
    One concept per company per measure, chosen as the one covering the most
    periods, and every other candidate left out of the series entirely.

    The collector already applies that rule when it decides what to fetch, and
    it is applied again here because the table outlives any one run of it. A
    company whose facts were collected under an older rule, or whose reporting
    tag changed between two runs, leaves both definitions sitting in the store,
    and a series stitched from two of them would show revenue jumping at the
    seam for reasons that have nothing to do with the company.
    """
    found = conn.execute(
        """
        with widest as (
          select concept
          from basis.company_fact
          where cik = %(cik)s and measure = %(measure)s and period_start is not null
          group by concept
          order by count(distinct period_end) desc, concept
          limit 1
        )
        select period_start, period_end, span_days, value, available_at,
               form, accession, f.concept, unit
        from basis.company_fact f
        join widest w on w.concept = f.concept
        where f.cik = %(cik)s and f.measure = %(measure)s
          and f.period_start is not null
        order by period_end, available_at
        """,
        {"cik": str(int(cik)), "measure": measure},
    ).fetchall()

    return [dict(row) for row in found]


def _derived_quarters(rows: list[dict], actions: list[dict]) -> list[dict]:
    """
    The fourth quarter, as the year minus the nine months inside it.

    The two facts are matched on period_start rather than on a calendar
    quarter, because a fiscal year that ends in September has a nine month
    period nobody would recognise from the date alone, and the start is the one
    field both filings agree on exactly.

    It becomes knowable when the later of the two does, which is always the
    annual figure, so a derived quarter is never available before the 10-K that
    completes it.
    """
    nine = {}
    for row in rows:
        if _within(row["span_days"], NINE_MONTHS):
            nine.setdefault(row["period_start"], []).append(row)

    derived = []
    for row in rows:
        if not _within(row["span_days"], YEAR):
            continue

        partial = nine.get(row["period_start"])
        if not partial:
            continue

        """
        The nine month figure has to have been reported by the time the annual
        one was, or the subtraction mixes a restated stub into a fresh year.
        """
        usable = [item for item in partial if item["available_at"] <= row["available_at"]]
        if not usable:
            continue

        stub = max(usable, key=lambda item: item["available_at"])

        """
        The two filings can sit either side of a split, so the stub is brought
        into the annual figure's units before the subtraction. Subtracting nine
        months counted in old shares from a year counted in new ones would
        produce a fourth quarter that never happened.
        """
        scale = split_factor(
            actions, stub["available_at"].date(), row["available_at"]
        ) if PER_SHARE in row["unit"] else 1.0

        derived.append(
            {
                "period_start": stub["period_end"],
                "period_end": row["period_end"],
                "value": float(row["value"]) - float(stub["value"]) / scale,
                "available_at": row["available_at"],
                "origin": "derived",
                "concept": row["concept"],
                "unit": row["unit"],
            }
        )

    return derived


def series(conn, cik: str, measure: str, actions: list[dict] = ()) -> list[dict]:
    """
    Every quarterly observation this company has, reported or derived, with the
    instant each became knowable. Vintages are kept: the same quarter appears
    once per filing that stated it, and choosing between them is the caller's
    question rather than this one's.
    """
    rows = _rows(conn, cik, measure)

    quarters = [
        {
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "value": row["value"],
            "available_at": row["available_at"],
            "origin": "reported",
            "concept": row["concept"],
            "unit": row["unit"],
        }
        for row in rows
        if _within(row["span_days"], QUARTER)
    ]

    """
    A quarter the company printed outranks one this code worked out, so the
    derived rows only fill periods that are otherwise absent.
    """
    printed = {row["period_end"] for row in quarters}
    quarters.extend(
        row
        for row in _derived_quarters(rows, actions)
        if row["period_end"] not in printed
    )

    return sorted(quarters, key=lambda row: (row["period_end"], row["available_at"]))


def known_at(rows: list[dict], moment: datetime) -> dict[date, dict]:
    """
    The series as it read at an instant: one value per quarter, the latest
    statement of it that had been filed by then. Strictly before rather than at
    or before, because a fact filed in the same second as the event is the
    event, and letting it in would hand the expectation the answer.
    """
    picked: dict[date, dict] = {}
    for row in rows:
        if row["available_at"] >= moment:
            continue
        current = picked.get(row["period_end"])
        if current is None or row["available_at"] > current["available_at"]:
            picked[row["period_end"]] = row
    return picked


def first_known(rows: list[dict], period_end: date) -> dict | None:
    """
    What the market first learned about a quarter, which is the first statement
    of it and never a restatement. A number revised two years later is a
    different fact and cannot be what a price reacted to.
    """
    stated = [row for row in rows if row["period_end"] == period_end]
    return min(stated, key=lambda row: row["available_at"]) if stated else None


def year_before(known: dict[date, dict], period_end: date) -> dict | None:
    """
    The same quarter of the previous year, matched by date rather than by
    counting back four places. A company that skips a filing would make the
    fourth place back a quarter and a half old, and comparing a summer against
    a spring is how seasonality gets read as growth.
    """
    candidates = [
        row
        for end, row in known.items()
        if YEAR_BEFORE[0] <= (period_end - end).days <= YEAR_BEFORE[1]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: abs((period_end - row["period_end"]).days - 365))
