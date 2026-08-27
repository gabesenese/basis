import numpy as np
import pandas as pd
import pytest

from basis.study import technical_gate


class Spy:
    """
    Records the size of every training slice it is handed, so the walk forward
    can be checked from the outside rather than by reading it.
    """

    def __init__(self, seen: list[int]):
        self.seen = seen

    def fit(self, features, target):
        self.seen.append(len(target))
        return self

    def predict_proba(self, features):
        return np.array([[0.4, 0.6]] * len(features))


def frame(rows: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {
            "day_close": np.linspace(1.10, 1.12, rows),
            "london_move_pips": rng.normal(size=rows),
            "momentum_5d_pips": rng.normal(size=rows),
            "from_pivot_pips": rng.normal(size=rows),
            "asian_position": rng.uniform(size=rows),
            "long_pips": rng.normal(size=rows),
            "short_pips": rng.normal(size=rows),
            "better_side": rng.choice(["long", "short"], size=rows),
        }
    )


def test_a_model_never_sees_the_session_it_predicts():
    """
    The training slice for index i must be exactly i rows long. One row more
    and the model has read the answer to the question it is being asked.
    """
    seen: list[int] = []
    features = np.arange(40).reshape(-1, 1).astype(float)
    target = np.tile([0, 1], 20)

    technical_gate.walk_forward(features, target, lambda: Spy(seen), warmup=10)

    assert seen == list(range(10, 40))


def test_sessions_before_the_warmup_are_left_unscored():
    features = np.arange(30).reshape(-1, 1).astype(float)
    target = np.tile([0, 1], 15)

    predictions = technical_gate.walk_forward(
        features, target, lambda: Spy([]), warmup=12
    )

    assert np.isnan(predictions[:12]).all()
    assert not np.isnan(predictions[12:]).any()


def test_the_walk_forward_is_reproducible():
    features = np.arange(60).reshape(-1, 1).astype(float)
    target = (np.arange(60) % 3 == 0).astype(int)
    build = technical_gate.models()["gradient_boosting"]

    first = technical_gate.walk_forward(features, target, build, warmup=30)
    second = technical_gate.walk_forward(features, target, build, warmup=30)

    np.testing.assert_array_equal(first, second)


def test_always_long_earns_the_long_column():
    data = frame()
    rules = technical_gate.naive_rules(data)

    assert rules["always_long"]["mean_pips"] == pytest.approx(data["long_pips"].mean())
    assert rules["always_short"]["mean_pips"] == pytest.approx(data["short_pips"].mean())


def test_the_coin_is_the_average_of_both_sides():
    data = frame()
    expected = ((data["long_pips"] + data["short_pips"]) / 2).mean()

    assert technical_gate.coin(data)["mean_pips"] == pytest.approx(expected)


def test_the_coin_scores_a_quarter_by_definition():
    assert technical_gate.coin(frame())["brier"] == 0.25


def test_fading_a_rule_is_the_mirror_of_following_it():
    data = frame()
    rules = technical_gate.naive_rules(data)

    assert rules["follow_london"]["sessions"] == rules["fade_london"]["sessions"]
    assert rules["follow_london"]["side_accuracy"] == pytest.approx(
        1 - rules["fade_london"]["side_accuracy"], abs=0.05
    )


def test_the_reported_interval_brackets_the_estimate():
    rules = technical_gate.naive_rules(frame())

    for rule in rules.values():
        assert rule["low"] <= rule["mean_pips"] <= rule["high"]
