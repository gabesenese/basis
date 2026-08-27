import numpy as np
import pandas as pd

from basis.study import fomc, gate

HORIZONS = ["ret_5m", "ret_30m", "ret_1h", "ret_2h", "ret_1d"]
GATE_HORIZON = "ret_2h"

"""
Three readings of the same 26 meetings, kept together because each is only
honest beside the others.

  decision    what the plan names as standardised surprise, the announced
              target range against the expectation priced the evening before
  path        the same expectation entered on its own, so the decision slope
              is read with the priced quarter held fixed
  repricing   how the curve moved across the announcement, which is not
              knowable at 14:00 and so diagnoses transmission rather than
              offering a signal
"""
TESTS = [
    {"key": "constrained", "regressors": ["z_surprise"], "tradable": True},
    {"key": "decomposed", "regressors": ["z_actual", "z_expected"], "tradable": True},
    {"key": "repricing", "regressors": ["z_reprice"], "tradable": False},
]


def _slope(slope: gate.Slope) -> dict:
    """
    A slope counts as evidence only when the robust interval and the bootstrap
    interval agree on excluding zero. Either one alone is a weaker claim than
    the sample size supports.
    """
    return {
        "name": slope.name,
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


def _fit(frame: pd.DataFrame, response: str, regressors: list[str]) -> dict:
    result = gate.fit(frame, response, regressors)
    return {
        "response": response,
        "n": int(result.n),
        "r_squared": float(result.r_squared),
        "slopes": [_slope(s) for s in result.slopes],
    }


def _clean(value):
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if pd.isna(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def assemble(conn) -> dict:
    frame = fomc.build(conn)

    tests = {
        test["key"]: {
            "regressors": test["regressors"],
            "tradable": test["tradable"],
            "by_horizon": {
                horizon: _fit(frame, horizon, test["regressors"])
                for horizon in HORIZONS
            },
        }
        for test in TESTS
    }

    loo_low, loo_high = gate.leave_one_out(
        frame, GATE_HORIZON, ["z_reprice"], "z_reprice"
    )

    magnitude = frame.assign(
        abs_reprice=frame["z_reprice"].abs(), abs_move=frame[GATE_HORIZON].abs()
    )
    rank_n, rho, rank_p = gate.spearman(magnitude, "abs_reprice", "abs_move")

    baseline = gate.baseline_moves(
        conn,
        frame["statement_time"].min().date(),
        frame["statement_time"].max().date(),
    )
    meeting_days = {t.date() for t in frame["statement_time"]}
    ordinary = baseline[~baseline["day"].isin(meeting_days)]

    event_median = float(frame[GATE_HORIZON].abs().median())
    ordinary_median = float(ordinary["move_pips"].abs().median())

    meetings = [
        {key: _clean(value) for key, value in record.items()}
        for record in frame.to_dict("records")
    ]

    return {
        "horizons": HORIZONS,
        "gate_horizon": GATE_HORIZON,
        "coverage": {
            "meetings": len(frame),
            "first": _clean(frame["statement_time"].min()),
            "last": _clean(frame["statement_time"].max()),
            "decisions_that_moved": int((frame["actual_bps"] != 0).sum()),
            "window_lead_days": {
                "min": int(frame["window_lead_days"].min()),
                "median": float(frame["window_lead_days"].median()),
                "max": int(frame["window_lead_days"].max()),
            },
        },
        "tests": tests,
        "leave_one_out": {"low": float(loo_low), "high": float(loo_high)},
        "magnitude": {"n": int(rank_n), "spearman": float(rho), "p_value": float(rank_p)},
        "event_versus_ordinary": {
            "event_n": len(frame),
            "event_median_pips": event_median,
            "ordinary_n": len(ordinary),
            "ordinary_median_pips": ordinary_median,
            "ratio": event_median / ordinary_median if ordinary_median else None,
        },
        "response_median_pips": {
            horizon: float(frame[horizon].abs().median()) for horizon in HORIZONS
        },
        "meetings": meetings,
    }
