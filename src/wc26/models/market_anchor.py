"""Market-anchored score grids (backlog #1, D028).

Solves for the Dixon-Coles lambdas that make penaltyblog's correct-score grid
reproduce a de-vigged market 1X2 quote, then prices team totals as marginals
of that market-consistent grid. This is the standard derivative-pricing
approach for props: the market consensus supplies the LEVEL (which the Phase 2
backtest shows it knows better than the engine — 0.9706 vs 0.9952 log-loss),
the grid supplies the SHAPE.

The solve is 2 unknowns (log-lambdas) from 2 constraints (P(home), P(away);
P(draw) is the complement). rho is a fixed input, NOT fitted: the headline
experiment uses rho=0 (zero fitted parameters → zero leakage risk), with a
rho=-0.05 sensitivity reported alongside (D028). All probability math goes
through penaltyblog (D003); scipy supplies the root-find only (D015 made
scipy an explicit dependency).

Pure functions, no I/O. All outputs are 90-minute probabilities (D004).
"""

import numpy as np
from numpy.typing import NDArray
from penaltyblog.models import FootballProbabilityGrid, create_dixon_coles_grid
from scipy.optimize import least_squares

MAX_GOALS = 15  # same grid truncation as goal_engine.predict_grid
_SOLVE_TOL = 1e-9
_RESIDUAL_CEILING = 1e-6
_LOG_LAM_BOUNDS = (np.log(0.02), np.log(8.0))


def _grid_home_away(
    log_lams: NDArray[np.float64], rho: float, max_goals: int
) -> tuple[float, float]:
    grid = create_dixon_coles_grid(
        float(np.exp(log_lams[0])), float(np.exp(log_lams[1])), rho=rho, max_goals=max_goals
    )
    p_home, _, p_away = (float(p) for p in grid.home_draw_away)
    return p_home, p_away


def solve_market_lambdas(
    p_home: float,
    p_away: float,
    rho: float = 0.0,
    max_goals: int = MAX_GOALS,
) -> tuple[float, float]:
    """(lam_home, lam_away) whose DC grid reproduces the de-vigged 1X2.

    `p_home`/`p_away` must be the FAIR (de-vigged, D005) win probabilities;
    pass raw implied probabilities and the recovered total-goals level will
    carry the vig. Raises if the probabilities are not a valid 3-way book
    (each in (0,1), sum < 1 so the draw keeps positive mass) or if the solve
    does not converge to the targets — a quote the grid cannot represent is
    a data problem to surface, never to paper over.

    Deterministic: fixed initial point, derivative-free trust-region solve.
    """
    for name, p in (("p_home", p_home), ("p_away", p_away)):
        if not 0.0 < p < 1.0:
            raise ValueError(f"{name} must be in (0, 1), got {p}")
    if p_home + p_away >= 1.0:
        raise ValueError(
            f"p_home + p_away = {p_home + p_away:.4f} >= 1 — no draw mass; "
            f"de-vig the quote first (D005)"
        )

    def residuals(log_lams: NDArray[np.float64]) -> NDArray[np.float64]:
        gh, ga = _grid_home_away(log_lams, rho, max_goals)
        return np.array([gh - p_home, ga - p_away], dtype=np.float64)

    # Start at a mid-scoring split leaning toward the favorite; the surface is
    # smooth and monotone in both lambdas, so the start barely matters.
    share = p_home / (p_home + p_away)
    x0 = np.log(np.array([2.6 * share, 2.6 * (1.0 - share)], dtype=np.float64))
    fit = least_squares(
        residuals,
        x0,
        bounds=_LOG_LAM_BOUNDS,
        xtol=_SOLVE_TOL,
        ftol=_SOLVE_TOL,
        gtol=_SOLVE_TOL,
    )
    worst = float(np.max(np.abs(fit.fun)))
    if worst > _RESIDUAL_CEILING:
        raise ValueError(
            f"market-lambda solve did not reach the quote "
            f"(p_home={p_home:.4f}, p_away={p_away:.4f}, rho={rho}): "
            f"max residual {worst:.2e}"
        )
    return float(np.exp(fit.x[0])), float(np.exp(fit.x[1]))


def market_anchored_grid(
    p_home: float,
    p_away: float,
    rho: float = 0.0,
    max_goals: int = MAX_GOALS,
) -> FootballProbabilityGrid:
    """Correct-score grid consistent with a de-vigged market 1X2 (90', D004)."""
    lam_home, lam_away = solve_market_lambdas(p_home, p_away, rho=rho, max_goals=max_goals)
    grid: FootballProbabilityGrid = create_dixon_coles_grid(
        lam_home, lam_away, rho=rho, max_goals=max_goals
    )
    return grid
