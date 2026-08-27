import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from basis.lanes import technical
from basis.study import daily

STOP_ATR = 0.5
TARGET_ATR = 0.75

"""
Two hundred and fifty sessions before the first prediction, so the earliest
model has about a year of history rather than a handful of days. Everything
after that is scored out of sample, one session at a time, refitting on
everything that had already closed.
"""
WARMUP = 250
SEED = 7


def models() -> dict:
    return {
        "logistic": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)
        ),
        "gradient_boosting": lambda: GradientBoostingClassifier(
            n_estimators=60, max_depth=2, random_state=SEED
        ),
    }


def walk_forward(features: np.ndarray, target: np.ndarray, build, warmup: int = WARMUP):
    """
    The session at index i is predicted by a model fit on rows 0 to i-1 and
    never on row i. That slice is the whole guarantee: a model that has seen
    the day it is predicting will look brilliant and cannot be traded.
    """
    predictions = np.full(len(target), np.nan)

    for index in range(warmup, len(target)):
        model = build()
        model.fit(features[:index], target[:index])
        predictions[index] = model.predict_proba(features[index : index + 1])[0, 1]

    return predictions


def _score(frame: pd.DataFrame, took_long: np.ndarray, mask: np.ndarray) -> dict:
    pips = np.where(took_long, frame["long_pips"].to_numpy()[mask],
                    frame["short_pips"].to_numpy()[mask])
    correct = np.where(took_long, "long", "short") == frame["better_side"].to_numpy()[mask]
    error = pips.std(ddof=1) / np.sqrt(len(pips))

    return {
        "sessions": int(len(pips)),
        "mean_pips": float(pips.mean()),
        "low": float(pips.mean() - 1.96 * error),
        "high": float(pips.mean() + 1.96 * error),
        "side_accuracy": float(correct.mean()),
    }


def naive_rules(frame: pd.DataFrame) -> dict:
    """
    The rules a person reaches for first, scored before any model exists. If a
    learned model cannot beat these, the features are the problem; if it cannot
    beat the coin, the whole approach is.
    """
    close = frame["day_close"]

    rules = {
        "always_long": np.ones(len(frame), bool),
        "always_short": np.zeros(len(frame), bool),
        "follow_london": frame["london_move_pips"].fillna(0).to_numpy() > 0,
        "fade_london": frame["london_move_pips"].fillna(0).to_numpy() < 0,
        "follow_prior_day": (close.shift(1) > close.shift(2)).fillna(False).to_numpy(),
        "follow_momentum_5d": frame["momentum_5d_pips"].fillna(0).to_numpy() > 0,
        "above_pivot": frame["from_pivot_pips"].fillna(0).to_numpy() > 0,
        "asian_breakout": frame["asian_position"].fillna(0.5).to_numpy() > 0.5,
    }

    everything = np.ones(len(frame), bool)
    return {name: _score(frame, took, everything) for name, took in rules.items()}


def coin(frame: pd.DataFrame, mask: np.ndarray | None = None) -> dict:
    mask = everything(frame) if mask is None else mask
    both = (frame["long_pips"].to_numpy()[mask] + frame["short_pips"].to_numpy()[mask]) / 2
    error = both.std(ddof=1) / np.sqrt(len(both))

    return {
        "sessions": int(len(both)),
        "mean_pips": float(both.mean()),
        "low": float(both.mean() - 1.96 * error),
        "high": float(both.mean() + 1.96 * error),
        "brier": 0.25,
    }


def everything(frame: pd.DataFrame) -> np.ndarray:
    return np.ones(len(frame), bool)


def assemble(conn, warmup: int = WARMUP) -> dict:
    frame = daily.build(conn, stop_atr=STOP_ATR, target_atr=TARGET_ATR)
    columns = [c for c in technical.FEATURE_COLUMNS if c in frame.columns]
    frame = frame.dropna(subset=columns).reset_index(drop=True)

    features = frame[columns].to_numpy(float)
    target = (frame["better_side"].to_numpy() == "long").astype(int)

    fits = {}
    scored = None
    for name, build in models().items():
        predictions = walk_forward(features, target, build, warmup)
        mask = ~np.isnan(predictions)
        scored = mask if scored is None else scored
        result = _score(frame, predictions[mask] > 0.5, mask)
        result["brier"] = float(np.mean((predictions[mask] - target[mask]) ** 2))
        fits[name] = result

    return {
        "trade": {"stop_atr": STOP_ATR, "target_atr": TARGET_ATR, "warmup": warmup},
        "sessions": int(len(frame)),
        "features": columns,
        "coin": coin(frame, scored),
        "naive_rules": naive_rules(frame),
        "fits": fits,
        "perfect_foresight_pips": float(
            frame[["long_pips", "short_pips"]].max(axis=1).mean()
        ),
        "worst_choice_pips": float(
            frame[["long_pips", "short_pips"]].min(axis=1).mean()
        ),
    }
