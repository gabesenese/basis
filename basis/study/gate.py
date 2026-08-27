from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

BOOTSTRAP_DRAWS = 20000
SEED = 20260826


@dataclass
class Slope:
    name: str
    estimate: float
    robust_low: float
    robust_high: float
    boot_low: float
    boot_high: float
    p_value: float


@dataclass
class Fit:
    response: str
    n: int
    r_squared: float
    slopes: list[Slope]


def fit(frame: pd.DataFrame, response: str, regressors: list[str]) -> Fit:
    """
    HC3 standard errors and a percentile bootstrap are reported together
    because they fail in different directions at this sample size. HC3 is the
    least optimistic of the sandwich family under small n, and the bootstrap
    drops the normal approximation entirely. A slope only counts as evidence
    when both intervals agree on excluding zero.
    """
    usable = frame[[response, *regressors]].dropna()
    y = usable[response].to_numpy(float)
    design = sm.add_constant(usable[regressors].to_numpy(float), has_constant="add")

    model = sm.OLS(y, design).fit(cov_type="HC3")
    robust = model.conf_int()

    rng = np.random.default_rng(SEED)
    draws = np.empty((BOOTSTRAP_DRAWS, design.shape[1]))
    for draw in range(BOOTSTRAP_DRAWS):
        pick = rng.integers(0, len(y), len(y))
        try:
            draws[draw] = np.linalg.lstsq(design[pick], y[pick], rcond=None)[0]
        except np.linalg.LinAlgError:
            draws[draw] = np.nan

    boot = np.nanpercentile(draws, [2.5, 97.5], axis=0)

    return Fit(
        response=response,
        n=len(y),
        r_squared=model.rsquared,
        slopes=[
            Slope(
                name=name,
                estimate=model.params[index],
                robust_low=robust[index][0],
                robust_high=robust[index][1],
                boot_low=boot[0][index],
                boot_high=boot[1][index],
                p_value=model.pvalues[index],
            )
            for index, name in enumerate(["intercept", *regressors], start=0)
        ],
    )


def leave_one_out(
    frame: pd.DataFrame, response: str, regressors: list[str], of: str
) -> tuple[float, float]:
    """
    Twenty six meetings is few enough that one of them can carry a slope on its
    own. Refitting without each in turn says whether the estimate is a property
    of the sample or of a single afternoon.
    """
    usable = frame[[response, *regressors]].dropna().reset_index(drop=True)
    index = regressors.index(of) + 1
    slopes = []

    for dropped in range(len(usable)):
        kept = usable.drop(index=dropped)
        design = sm.add_constant(kept[regressors].to_numpy(float), has_constant="add")
        model = sm.OLS(kept[response].to_numpy(float), design).fit()
        slopes.append(model.params[index])

    return min(slopes), max(slopes)


def spearman(frame: pd.DataFrame, left: str, right: str) -> tuple[int, float, float]:
    usable = frame[[left, right]].dropna()
    result = stats.spearmanr(usable[left], usable[right])
    return len(usable), float(result.statistic), float(result.pvalue)


def sign_agreement(frame: pd.DataFrame, surprise: str, response: str) -> dict:
    """
    A hawkish surprise should sell EUR/USD, so agreement is a sign flip between
    the two. Meetings where the surprise is exactly zero carry no direction and
    are excluded rather than scored as a miss.
    """
    usable = frame[[surprise, response]].dropna()
    usable = usable[usable[surprise] != 0]

    agree = int((np.sign(usable[surprise]) != np.sign(usable[response])).sum())
    total = len(usable)
    if total == 0:
        return {"n": 0}

    interval = stats.binomtest(agree, total, 0.5).proportion_ci(0.95)
    return {
        "n": total,
        "agree": agree,
        "rate": agree / total,
        "low": interval.low,
        "high": interval.high,
        "p_value": stats.binomtest(agree, total, 0.5).pvalue,
    }


def baseline_moves(conn, start, finish, clock: str = "14:00") -> pd.DataFrame:
    """
    The same two hour window on every ordinary session, taken from the same
    clock time so the comparison is against the market's own afternoon rather
    than against a full day average that mixes the Asian session in.
    """
    rows = conn.execute(
        """
        with days as (
            select generate_series(%s::date, %s::date, interval '1 day')::date as day
        ),
        moments as (
            select day, (day + %s::time) at time zone 'America/New_York' as opens
            from days
        )
        select m.day, m.opens,
          (select (bid_close + ask_close) / 2
             from basis.price_bar p
            where p.instrument_id = 'EUR_USD' and p.granularity = 'M1'
              and p.effective_time <= m.opens - interval '1 minute'
              and p.effective_time > m.opens - interval '11 minutes'
            order by p.effective_time desc limit 1) as entry,
          (select (bid_close + ask_close) / 2
             from basis.price_bar p
            where p.instrument_id = 'EUR_USD' and p.granularity = 'M1'
              and p.effective_time <= m.opens + interval '119 minutes'
              and p.effective_time > m.opens + interval '109 minutes'
            order by p.effective_time desc limit 1) as exit
        from moments m
        """,
        (start, finish, clock),
    ).fetchall()

    frame = pd.DataFrame(rows).dropna()
    frame["move_pips"] = (
        frame["exit"].astype(float) - frame["entry"].astype(float)
    ) / 0.0001
    return frame
