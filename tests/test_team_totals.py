"""Team-totals model: marginals must agree with penaltyblog's own outputs."""

import numpy as np
import pytest
from penaltyblog.models import create_dixon_coles_grid

from wc26.models.team_totals import (
    distribution_mean_var,
    goal_marginals,
    p_over,
    total_distribution,
)

GRID = create_dixon_coles_grid(1.4, 1.1, rho=-0.05, max_goals=15)


def test_marginals_are_distributions() -> None:
    home, away = goal_marginals(GRID)
    assert home.sum() == pytest.approx(1.0)
    assert away.sum() == pytest.approx(1.0)
    assert home.min() >= 0 and away.min() >= 0


def test_marginal_means_match_grid_expectations() -> None:
    home, away = goal_marginals(GRID)
    h_mean, _ = distribution_mean_var(home)
    a_mean, _ = distribution_mean_var(away)
    # Truncation+renormalization shifts the mean by < 0.1%.
    assert h_mean == pytest.approx(float(GRID.home_goal_expectation), rel=2e-3)
    assert a_mean == pytest.approx(float(GRID.away_goal_expectation), rel=2e-3)


def test_total_over_matches_penaltyblog() -> None:
    total = total_distribution(GRID)
    for line in (1.5, 2.5, 3.5):
        assert p_over(total, line) == pytest.approx(float(GRID.total_goals("over", line)), abs=1e-9)


def test_p_over_hand_computed() -> None:
    dist = np.array([0.2, 0.3, 0.5])
    assert p_over(dist, 0.5) == pytest.approx(0.8)
    assert p_over(dist, 1.5) == pytest.approx(0.5)


def test_p_over_rejects_whole_lines() -> None:
    dist = np.array([0.5, 0.5])
    with pytest.raises(ValueError, match="half-integer"):
        p_over(dist, 2.0)


def test_distribution_mean_var_hand_computed() -> None:
    dist = np.array([0.5, 0.0, 0.5])
    mean, var = distribution_mean_var(dist)
    assert mean == pytest.approx(1.0)
    assert var == pytest.approx(1.0)
