"""Backtest mechanics on synthetic data: scoring rules, Elo baseline,
eval-set construction with D012/D013 handling. No real data needed."""

import numpy as np
import pandas as pd
import pytest

from wc26.backtest.baselines import devig_1x2, fit_elo_baseline
from wc26.backtest.harness import build_eval_set
from wc26.backtest.metrics import brier, log_loss


def test_log_loss_hand_computed() -> None:
    probs = np.array([[0.5, 0.3, 0.2], [0.1, 0.6, 0.3]])
    outcomes = np.array([0, 2], dtype=np.int64)
    expected = -(np.log(0.5) + np.log(0.3)) / 2
    assert log_loss(probs, outcomes) == pytest.approx(expected)


def test_brier_hand_computed() -> None:
    probs = np.array([[0.5, 0.3, 0.2]])
    outcomes = np.array([1], dtype=np.int64)
    expected = 0.5**2 + 0.7**2 + 0.2**2
    assert brier(probs, outcomes) == pytest.approx(expected)


def test_metrics_reject_bad_inputs() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        log_loss(np.array([[0.9, 0.3, 0.2]]), np.array([0], dtype=np.int64))
    with pytest.raises(ValueError, match=r"\(n, 3\)"):
        brier(np.array([[0.5, 0.5]]), np.array([0], dtype=np.int64))


def test_elo_baseline_properties() -> None:
    rng = np.random.default_rng(3)
    n = 600
    elo_home = rng.uniform(1400, 2000, n)
    elo_away = rng.uniform(1400, 2000, n)
    neutral = rng.random(n) < 0.5
    dr = elo_home - elo_away + np.where(neutral, 0, 100.0)
    # Outcomes drawn from a simple dr-driven truth with ~25% draws.
    p_home = 1 / (1 + 10 ** (-(dr - 80) / 400))
    p_away = 1 / (1 + 10 ** ((dr + 80) / 400))
    u = rng.random(n)
    outcomes = np.where(u < p_home, 0, np.where(u > 1 - p_away, 2, 1)).astype(np.int64)

    baseline = fit_elo_baseline(elo_home, elo_away, neutral, outcomes)
    assert 1.0 < baseline.nu < 400.0

    probs = baseline.predict(elo_home, elo_away, neutral)
    assert probs.shape == (n, 3)
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert (probs > 0).all()
    # Higher rating difference -> higher home win probability.
    strong = baseline.predict(np.array([1900.0]), np.array([1500.0]), np.array([True]))
    weak = baseline.predict(np.array([1600.0]), np.array([1500.0]), np.array([True]))
    assert strong[0, 0] > weak[0, 0]
    # Home advantage worth +100: neutral=False shifts toward the home side.
    at_home = baseline.predict(np.array([1600.0]), np.array([1600.0]), np.array([False]))
    assert at_home[0, 0] > at_home[0, 2]


def test_devig_multiplicative_sums_to_one() -> None:
    probs = devig_1x2(np.array([[2.63, 3.12, 2.84], [1.46, 4.32, 8.92]]))
    assert np.allclose(probs.sum(axis=1), 1.0)
    # Vig removal keeps proportions: implied 1/2.63 etc., normalized.
    raw = 1 / np.array([2.63, 3.12, 2.84])
    assert probs[0] == pytest.approx(raw / raw.sum())


def _mini_world() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    results = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-12-01", "2022-12-03", "2022-12-18"]),
            "home_id": ["aaa", "ccc", "eee"],
            "away_id": ["bbb", "ddd", "fff"],
            "home_score": [2, 0, 3],
            "away_score": [1, 0, 3],
            "tournament": ["FIFA World Cup"] * 3,
            "tier": ["world_cup"] * 3,
            "neutral": [True, True, True],
        }
    )
    # Odds dated one day off and with home/away swapped for the first match:
    # both D013 tolerances must engage.
    market_odds = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-12-02", "2022-12-03", "2022-12-18"]),
            "tournament": ["FIFA World Cup"] * 3,
            "home_id": ["bbb", "ccc", "eee"],
            "away_id": ["aaa", "ddd", "fff"],
            "odds_home": [4.0, 3.0, 2.5],
            "odds_draw": [3.5, 3.2, 3.3],
            "odds_away": [1.8, 2.4, 2.9],
            "source": ["test"] * 3,
        }
    )
    # The 3-3 on Dec 18 went to extra time (was 2-2 after 90').
    match_stats = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-12-18"]),
            "home_id": ["eee"],
            "away_id": ["fff"],
            "extra_time": [True],
        }
    )
    return results, match_stats, market_odds


def test_build_eval_set_handles_swap_drift_and_extra_time() -> None:
    results, match_stats, market_odds = _mini_world()
    eval_set = build_eval_set(market_odds, results, match_stats)
    assert len(eval_set) == 3

    swapped = eval_set[eval_set["home_id"] == "aaa"].iloc[0]
    assert swapped["outcome"] == 0  # aaa won 2-1
    assert swapped["odds_home"] == 1.8  # odds flipped along with the teams
    assert swapped["odds_away"] == 4.0

    goalless = eval_set[eval_set["home_id"] == "ccc"].iloc[0]
    assert goalless["outcome"] == 1
    assert not goalless["extra_time"]

    et_match = eval_set[eval_set["home_id"] == "eee"].iloc[0]
    assert et_match["extra_time"]
    assert et_match["outcome"] == 1  # draw after 90' regardless of stored 3-3


def test_build_eval_set_raises_on_unmatched_odds() -> None:
    results, match_stats, market_odds = _mini_world()
    orphan = market_odds.copy()
    orphan.loc[0, "home_id"] = "zzz"
    with pytest.raises(ValueError, match="check aliases"):
        build_eval_set(orphan, results, match_stats)
