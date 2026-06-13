"""WC scoring-offset experiment verdict (D035, backlog #4).

Pins the experiment result: the offset is a real, gate-safe LOG-LOSS/level
improvement on World Cup matches that does NOT fix the calibration slope (a
level shift can't — D019). It is built into the engine but default OFF
(predict_grid apply_finals_offset=False); these tests guard the verdict so a
silent flip can't happen without a DECISIONS entry. Artifact tests skip on a
fresh clone, per repo convention.

Also a unit test that the offset is estimated and applied correctly.
"""

import json

import numpy as np
import pytest

from wc26.backtest.wc_offset import WC_OFFSET_SUMMARY_JSON


def test_offset_estimation_and_application_are_consistent() -> None:
    """_estimate_finals_offset re-levels a tiny WC training set, and
    predict_grid(apply_finals_offset=True) scales both lambdas by exp(delta)."""
    import pandas as pd

    from wc26.models.goal_engine import (
        MIN_WC_MATCHES_FOR_OFFSET,
        TeamStrength,
        _estimate_finals_offset,
        predict_grid,
    )

    teams = {"a": TeamStrength(0.2, -0.1, 50.0), "b": TeamStrength(0.0, 0.0, 50.0)}
    # Build a WC training frame where realized totals exceed the model's
    # ~exp(0.1)+exp(-0.1) ≈ 2.1 predicted, so delta > 0.
    n = MIN_WC_MATCHES_FOR_OFFSET + 5
    train = pd.DataFrame(
        {
            "tier": ["world_cup"] * n,
            "home_id": ["a"] * n,
            "away_id": ["b"] * n,
            "neutral": [True] * n,
            "home_score": [2] * n,
            "away_score": [1] * n,  # realized total 3.0 >> predicted ~2.1
        }
    )
    delta = _estimate_finals_offset(train, teams, home_advantage=0.25)
    assert delta > 0.0

    from types import SimpleNamespace

    params = SimpleNamespace(
        teams=teams, home_advantage=0.25, rho=0.0, data_cutoff="x", finals_scoring_offset=delta
    )
    base = predict_grid(params, "a", "b", neutral=True)  # type: ignore[arg-type]
    off = predict_grid(params, "a", "b", neutral=True, apply_finals_offset=True)  # type: ignore[arg-type]
    base_total = float(base.home_goal_expectation) + float(base.away_goal_expectation)
    off_total = float(off.home_goal_expectation) + float(off.away_goal_expectation)
    assert off_total == pytest.approx(base_total * np.exp(delta), rel=1e-6)


def test_too_few_wc_rows_gives_zero_offset() -> None:
    import pandas as pd

    from wc26.models.goal_engine import TeamStrength, _estimate_finals_offset

    teams = {"a": TeamStrength(0.2, -0.1, 50.0), "b": TeamStrength(0.0, 0.0, 50.0)}
    train = pd.DataFrame(
        {
            "tier": ["world_cup"] * 3,
            "home_id": ["a"] * 3,
            "away_id": ["b"] * 3,
            "neutral": [True] * 3,
            "home_score": [5] * 3,
            "away_score": [5] * 3,
        }
    )
    assert _estimate_finals_offset(train, teams, 0.25) == 0.0


def test_default_predict_grid_has_no_offset() -> None:
    """The engine ships with the offset OFF: a default predict equals an
    explicit apply_finals_offset=False even when delta != 0."""
    from types import SimpleNamespace

    from wc26.models.goal_engine import TeamStrength, predict_grid

    params = SimpleNamespace(
        teams={"a": TeamStrength(0.1, 0.0, 50.0), "b": TeamStrength(0.0, 0.0, 50.0)},
        home_advantage=0.2,
        rho=0.0,
        data_cutoff="x",
        finals_scoring_offset=0.3,
    )
    a = predict_grid(params, "a", "b", neutral=False)  # type: ignore[arg-type]
    b = predict_grid(params, "a", "b", neutral=False, apply_finals_offset=False)  # type: ignore[arg-type]
    assert float(a.home_goal_expectation) == pytest.approx(float(b.home_goal_expectation))


needs_artifact = pytest.mark.skipif(
    not WC_OFFSET_SUMMARY_JSON.exists(),
    reason="wc_offset artifact missing — run `uv run wc26 backtest`",
)


@needs_artifact
def test_offset_improves_logloss_but_not_slope() -> None:
    """D035 verdict pin: on the WC subset the offset improves 1X2 AND
    team-total log-loss and moves the total level toward realized, while the
    O1.5 slope does NOT enter the gate band (level != spread). A future flip of
    either fact breaks this and forces a DECISIONS entry."""
    with WC_OFFSET_SUMMARY_JSON.open() as f:
        s = json.load(f)
    b, o = s["base"], s["offset"]
    assert o["x1x2_log_loss"] < b["x1x2_log_loss"], "offset no longer helps WC 1X2 — revisit D035"
    assert o["team_count_log_loss"] < b["team_count_log_loss"]
    assert o["match_count_log_loss"] < b["match_count_log_loss"]
    # level moves up toward realized (under-corrects: still below realized)
    assert b["pred_total_mean"] < o["pred_total_mean"] <= o["realized_total_mean"]
    # the slope is NOT fixed by a level offset (stays below the gate band)
    assert o["team_o15_slope"] < 0.8
