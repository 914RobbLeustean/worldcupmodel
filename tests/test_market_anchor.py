"""Market-anchor solver tests + experiment-artifact gates (D028).

Solver tests are pure-math round trips (no I/O): a grid built from known
lambdas yields exact 1X2 probabilities; the solver must recover the lambdas.
Artifact tests skip when the experiment has never been run (fresh clone),
per repo convention.
"""

import json

import numpy as np
import pytest
from penaltyblog.models import create_dixon_coles_grid

from wc26.backtest.market_anchor import ANCHOR_PARQUET, ANCHOR_SUMMARY_JSON
from wc26.config import load_settings
from wc26.models.market_anchor import market_anchored_grid, solve_market_lambdas


def _targets(lam_home: float, lam_away: float, rho: float) -> tuple[float, float]:
    grid = create_dixon_coles_grid(lam_home, lam_away, rho=rho, max_goals=15)
    p_home, _, p_away = (float(p) for p in grid.home_draw_away)
    return p_home, p_away


@pytest.mark.parametrize(
    ("lam_home", "lam_away", "rho"),
    [
        (1.8, 0.9, 0.0),
        (1.1, 1.1, 0.0),
        (2.6, 0.4, 0.0),  # heavy mismatch — the WC favorite case
        (1.5, 1.0, -0.06),
    ],
)
def test_solver_round_trip_recovers_lambdas(lam_home: float, lam_away: float, rho: float) -> None:
    p_home, p_away = _targets(lam_home, lam_away, rho)
    got_home, got_away = solve_market_lambdas(p_home, p_away, rho=rho)
    assert abs(got_home - lam_home) < 1e-4
    assert abs(got_away - lam_away) < 1e-4


def test_anchored_grid_reproduces_the_quote() -> None:
    grid = market_anchored_grid(0.50, 0.22, rho=0.0)
    p_home, _, p_away = (float(p) for p in grid.home_draw_away)
    assert abs(p_home - 0.50) < 1e-6
    assert abs(p_away - 0.22) < 1e-6


def test_solver_is_deterministic() -> None:
    a = solve_market_lambdas(0.41, 0.31)
    b = solve_market_lambdas(0.41, 0.31)
    assert a == b


@pytest.mark.parametrize(
    ("p_home", "p_away"),
    [(0.0, 0.3), (1.0, 0.3), (0.3, 0.0), (0.7, 0.3), (0.6, 0.5)],
)
def test_solver_rejects_invalid_probabilities(p_home: float, p_away: float) -> None:
    with pytest.raises(ValueError):
        solve_market_lambdas(p_home, p_away)


needs_anchor = pytest.mark.skipif(
    not (ANCHOR_PARQUET.exists() and ANCHOR_SUMMARY_JSON.exists()),
    reason="market-anchor artifacts missing — run `uv run wc26 backtest`",
)


@pytest.fixture(scope="module")
def summary() -> dict:  # type: ignore[type-arg]
    with ANCHOR_SUMMARY_JSON.open() as f:
        loaded: dict = json.load(f)  # type: ignore[type-arg]
        return loaded


@needs_anchor
def test_anchor_artifact_covers_the_props_sample(summary: dict) -> None:  # type: ignore[type-arg]
    # Identical-row comparison: the experiment must cover the full 191-row
    # non-ET props eval (D017), one market quote joined per row.
    assert summary["n"] == 191
    ll = summary["team_count_log_loss"]
    assert np.isfinite(ll["anchored"]) and np.isfinite(ll["engine"]) and np.isfinite(ll["naive"])


@needs_anchor
def test_blend_weight_is_fit_on_the_full_1x2_sample(summary: dict) -> None:  # type: ignore[type-arg]
    blend = summary["blend_1x2"]
    assert blend["n"] == 211
    assert 0.0 <= blend["w_star"] <= 1.0
    # Sanity: the blend at w* can never be worse than either endpoint.
    assert blend["log_loss_at_w_star"] <= blend["log_loss_engine_only"] + 1e-12
    assert blend["log_loss_at_w_star"] <= blend["log_loss_market_only"] + 1e-12


@needs_anchor
def test_anchored_pricing_justification_pinned(summary: dict) -> None:  # type: ignore[type-arg]
    """D028 verdict pin (the D021 pattern, in the passing direction).

    Live team-total pricing moves to market-anchored grids BECAUSE the
    anchored grid beats the engine on the walk-forward sample and its
    calibration slope sits in the gate range (2026-06-12: 1.3897 vs 1.4051;
    slope 0.864). If a refit ever flips either fact, this fails loudly and
    forces a DECISIONS entry, not a silent re-pivot.
    """
    settings = load_settings()
    ll = summary["team_count_log_loss"]
    assert ll["anchored"] < ll["engine"], "anchored grid no longer beats the engine — revisit D028"
    assert ll["anchored"] < ll["naive"]
    slope = summary["team_o15"]["anchored_calibration_slope"]
    assert settings.props.calibration_slope_min <= slope <= settings.props.calibration_slope_max


@needs_anchor
def test_engine_opinion_weight_stays_token(summary: dict) -> None:  # type: ignore[type-arg]
    """D028: the engine's 1X2 opinion earned w*=0.00 against the market over
    211 matches — raw `model_p - fair_p` edges are noise, not signal. If w*
    ever climbs materially, the no-engine-opinion betting rule needs
    re-deciding (DECISIONS entry), so pin a ceiling well above noise drift."""
    assert summary["blend_1x2"]["w_star"] <= 0.15
