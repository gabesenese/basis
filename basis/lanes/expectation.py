from datetime import date, datetime
from statistics import median, stdev

from psycopg.types.json import Jsonb

from basis.lanes import fundamentals

SOURCE_ID = "basis_seasonal_naive"

"""
The other half of a surprise, and the half nobody publishes for free.

A gap is not news until there is a number the release can be read against.
Consensus is sold rather than given, so what this builds instead is the
company's own history: the same quarter a year ago, carried forward by however
much the four quarters since have grown. It is a weak forecast on purpose. It
costs nothing, it is reproducible from filings alone, and it is a floor rather
than a ceiling: whatever a bought consensus is worth, it is worth the
difference between it and this.

What it is not is what the market expected. Analysts know about a product
launch, a guidance cut and a currency move, and this rule knows about four
numbers. Every result measured against it is therefore a lower bound on what a
real expectation would find, and reading it as anything else would be reading a
naive model as a market.
"""

DRIFT_WINDOW = 4

"""
Two year-over-year changes is the fewest a median can be taken of without it
being one number wearing a disguise.
"""
MIN_CHANGES = 2

RESIDUAL_WINDOW = 12
MIN_RESIDUALS = 6


def predict(known: dict[date, dict], period_end: date) -> dict | None:
    """
    The same quarter last year, moved by the drift of the four quarters before
    this one.

    The drift is multiplicative when every number it touches is positive, which
    is how revenue behaves and is the only form in which growth compounds. It
    turns additive the moment a negative appears, because a ratio across zero
    is not a rate of change, it is an artefact, and an earnings per share series
    crosses zero often enough that this is the ordinary case rather than the
    defensive one. Which rule answered is stored with the number.
    """
    base = fundamentals.year_before(known, period_end)
    if base is None:
        return None

    changes = []
    for end in sorted(end for end in known if end < period_end)[-DRIFT_WINDOW:]:
        against = fundamentals.year_before(known, end)
        if against is None:
            continue
        changes.append((float(known[end]["value"]), float(against["value"])))

    if len(changes) < MIN_CHANGES:
        return None

    anchor = float(base["value"])
    compounding = anchor > 0 and all(now > 0 and then > 0 for now, then in changes)

    if compounding:
        drift = median(now / then for now, then in changes)
        expected = anchor * drift
    else:
        drift = median(now - then for now, then in changes)
        expected = anchor + drift

    return {
        "expected": expected,
        "rule": "multiplicative" if compounding else "additive",
        "drift": drift,
        "anchor": anchor,
        "anchor_period": base["period_end"].isoformat(),
        "anchor_origin": base["origin"],
        "changes": len(changes),
    }


def _residuals(known: dict[date, dict], period_end: date) -> list[float]:
    """
    How wrong this rule has been on this company, which is the unit a surprise
    is expressed in.

    Each past quarter is predicted from the quarters before it and nothing
    after, so no residual is computed from its own answer. What the residuals do
    carry is the vintage of the moment they are built at rather than of the
    quarter they describe: a restatement filed last year changes a residual from
    three years ago. That is a known impurity and it is bounded in the direction
    that matters, since every value involved was already knowable before the
    event being measured.
    """
    found = []
    for end in sorted((end for end in known if end < period_end), reverse=True):
        guess = predict({k: v for k, v in known.items() if k < end}, end)
        if guess is None:
            continue
        found.append(float(known[end]["value"]) - guess["expected"])
        if len(found) >= RESIDUAL_WINDOW:
            break
    return found


def estimate(rows: list[dict], moment: datetime, period_end: date) -> dict | None:
    """
    The expectation as it stood an instant before the release, and the scale to
    read it in. Everything it touches was filed strictly before `moment`, which
    is what stops the quarter being reported from predicting itself.
    """
    known = fundamentals.known_at(rows, moment)

    guess = predict(known, period_end)
    if guess is None:
        return None

    residuals = _residuals(known, period_end)
    if len(residuals) < MIN_RESIDUALS:
        return None

    scale = stdev(residuals)
    if scale <= 0:
        return None

    return {
        **guess,
        "scale": scale,
        "residuals": len(residuals),
        "period_end": period_end.isoformat(),
    }


def surprise(actual: float, estimate: dict) -> float:
    return (actual - estimate["expected"]) / estimate["scale"]


def ingest(
    conn, event_key: str, measure: str, moment: datetime, estimate: dict
) -> int:
    """
    effective_time and available_at are both the release instant, and the
    equality is the point. The estimate describes the information set at that
    instant and was built only from filings strictly before it, so it was
    knowable exactly then. Nothing here records when this process got around to
    computing it, for the same reason a text label records publication rather
    than processing.
    """
    result = conn.execute(
        """
        insert into basis.expectation
          (event_key, source_id, measure, effective_time, available_at,
           point_value, distribution)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (event_key, source_id, measure, effective_time, available_at)
        do nothing
        """,
        (
            event_key,
            SOURCE_ID,
            measure,
            moment,
            moment,
            estimate["expected"],
            Jsonb(estimate),
        ),
    )
    return result.rowcount
