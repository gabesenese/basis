from datetime import datetime, timedelta

import pandas as pd

from basis.sources import dukascopy as dk
from basis.sources import oanda


def compare_hour(hour: datetime, symbol: str = "EURUSD", instrument: str = "EUR_USD") -> dict:
    """
    Holds the two feeds against each other over one hour. Mid agreement says
    they are quoting the same market; spread disagreement says nothing about
    correctness, because a raw ECN book and a market maker quote are different
    products. Only the venue we actually trade through can price the hurdle.
    """
    with dk.open_client() as client:
        ticks = dk.fetch_hour(client, symbol, hour)
    if ticks.empty:
        return {"hour": hour, "minutes": 0}

    with oanda.open_client() as client:
        bars = oanda.candles(client, instrument, "M1", start=hour, count=60)
    if bars.empty:
        return {"hour": hour, "minutes": 0}

    indexed = ticks.set_index("ts")
    per_minute = pd.DataFrame(
        {
            "dk_mid": ((indexed["bid"] + indexed["ask"]) / 2).resample("1min").last(),
            "dk_spread": ((indexed["ask"] - indexed["bid"]) * 10000).resample("1min").median(),
        }
    ).dropna()

    bars = bars.set_index("ts")
    merged = per_minute.join(
        pd.DataFrame(
            {
                "oa_mid": (bars["bid_close"] + bars["ask_close"]) / 2,
                "oa_spread": (bars["ask_close"] - bars["bid_close"]) * 10000,
            }
        ),
        how="inner",
    )
    if merged.empty:
        return {"hour": hour, "minutes": 0}

    difference = (merged["dk_mid"] - merged["oa_mid"]) * 10000

    return {
        "hour": hour,
        "minutes": len(merged),
        "mid_median_pips": float(difference.median()),
        "mid_p05_pips": float(difference.quantile(0.05)),
        "mid_p95_pips": float(difference.quantile(0.95)),
        "mid_worst_pips": float(difference.abs().max()),
        "dukascopy_spread_median": float(merged["dk_spread"].median()),
        "oanda_spread_median": float(merged["oa_spread"].median()),
        "spread_ratio": float(merged["oa_spread"].median() / merged["dk_spread"].median()),
    }


def report(hours: list[datetime]) -> pd.DataFrame:
    rows = [compare_hour(hour) for hour in hours]
    return pd.DataFrame([r for r in rows if r.get("minutes")])
