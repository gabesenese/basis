from dataclasses import dataclass

import pandas as pd

BASELINE_FROM = -1800
BASELINE_TO = -300

BUCKETS = [
    (-300, -60), (-60, -15), (-15, -5), (-5, 0),
    (0, 2), (2, 5), (5, 10), (10, 20), (20, 40),
    (40, 90), (90, 300), (300, 900),
]


@dataclass(frozen=True)
class SpreadEstimate:
    pips: float
    provenance: str
    basis: str

    @property
    def measured(self) -> bool:
        return self.provenance == "measured"


def measure_profile(con, events, source: str, symbol: str) -> pd.DataFrame:
    """
    The shape of the blowout, expressed as a multiple of each event's own quiet
    baseline rather than in pips.

    Normalising per event is what makes the shape transferable. Absolute pips
    belong to the venue that quoted them, but the ratio between the release
    second and the calm half hour before it is a property of how the market
    behaves around a scheduled release, and that is the part worth carrying
    across to a venue whose own history cannot be measured.
    """
    rows = []

    for event in events:
        ticks = con.execute(
            """
            select epoch(ts - ?::timestamptz) as rel, (ask - bid) * 10000 as spread
            from ticks
            where source = ? and symbol = ?
              and ts between ?::timestamptz - interval '30 min'
                         and ?::timestamptz + interval '15 min'
            """,
            [event, source, symbol, event, event],
        ).df()

        if ticks.empty:
            continue

        quiet = ticks[(ticks["rel"] >= BASELINE_FROM) & (ticks["rel"] < BASELINE_TO)]["spread"]
        if len(quiet) < 30:
            continue
        baseline = quiet.median()
        if baseline <= 0:
            continue

        for low, high in BUCKETS:
            window = ticks[(ticks["rel"] >= low) & (ticks["rel"] < high)]["spread"]
            if window.empty:
                continue
            rows.append({
                "bucket_from": low,
                "bucket_to": high,
                "median_ratio": window.median() / baseline,
                "p95_ratio": window.quantile(0.95) / baseline,
                "max_ratio": window.max() / baseline,
                "baseline_pips": baseline,
                "event": event,
            })

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    return (
        frame.groupby(["bucket_from", "bucket_to"])
        .agg(
            median_ratio=("median_ratio", "median"),
            p95_ratio=("p95_ratio", "median"),
            max_ratio=("max_ratio", "median"),
            events=("event", "nunique"),
        )
        .reset_index()
        .sort_values("bucket_from")
    )


def estimate(profile: pd.DataFrame, baseline_pips: float, seconds_from_event: float,
             quantile: str = "p95_ratio") -> SpreadEstimate:
    """
    Applies a shape measured on one venue to another venue's baseline.

    The result is a modelled number and says so. Nothing downstream is allowed
    to mistake it for an observation, because the transfer assumes both venues
    widen by the same proportion, and that assumption is untested until the
    recorder has captured real releases on the venue we trade.
    """
    if profile.empty:
        return SpreadEstimate(baseline_pips, "unavailable", "no profile measured")

    match = profile[
        (profile["bucket_from"] <= seconds_from_event)
        & (profile["bucket_to"] > seconds_from_event)
    ]
    if match.empty:
        return SpreadEstimate(baseline_pips, "modelled", "outside the measured window")

    ratio = float(match.iloc[0][quantile])
    return SpreadEstimate(
        pips=baseline_pips * ratio,
        provenance="modelled",
        basis=f"dukascopy shape {ratio:.2f}x applied to a {baseline_pips:.2f} pip baseline",
    )
