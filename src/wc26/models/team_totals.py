"""Team-totals prop model (Phase 3.1): marginals of the goal engine grid.

The goal engine's correct-score grid already contains the home/away goal
distributions; this module extracts them and prices over/under any half-goal
line. No separate fit — the model version IS the goal engine version, and
the walk-forward totals backtest (src/wc26/backtest/props.py) is the
evidence it may price lines.

Dispersion: Phase 2 flagged engine match-totals as under-dispersed vs the
market. The backtest quantifies dispersion against OUTCOMES (variance ratio
+ calibration slope + count log-loss vs the naive baseline); the verdict and
the no-rescale rationale live in DECISIONS.md D019 and docs/MODEL.md. Do not
add a correction here without a new DECISIONS entry.

All outputs are 90-minute distributions (D004).
"""

import numpy as np
from numpy.typing import NDArray
from penaltyblog.models import FootballProbabilityGrid


def goal_marginals(
    grid: FootballProbabilityGrid,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """(home, away) goal count distributions from the correct-score grid.

    The grid is truncated at max_goals, so mass sums to slightly under 1;
    marginals are renormalized so downstream log-loss math is well-formed.
    """
    matrix = np.asarray(grid.grid, dtype=np.float64)
    home = matrix.sum(axis=1)
    away = matrix.sum(axis=0)
    return home / home.sum(), away / away.sum()


def total_distribution(grid: FootballProbabilityGrid) -> NDArray[np.float64]:
    """Match total-goals distribution (sum over grid anti-diagonals)."""
    matrix = np.asarray(grid.grid, dtype=np.float64)
    n = matrix.shape[0]
    total = np.zeros(2 * n - 1, dtype=np.float64)
    for h in range(n):
        for a in range(n):
            total[h + a] += matrix[h, a]
    return np.asarray(total / total.sum(), dtype=np.float64)


def p_over(dist: NDArray[np.float64], line: float) -> float:
    """P(count > line) for a half-goal line (2.5, 1.5, ...).

    Whole-number lines push (stake returned on exact hit) — refuse them here;
    pricing pushes is a markets-layer concern, not a distribution one.
    """
    if (2 * line) % 2 != 1:
        raise ValueError(f"line must be a half-integer (x.5), got {line}")
    threshold = int(np.ceil(line))
    return float(dist[threshold:].sum())


def distribution_mean_var(dist: NDArray[np.float64]) -> tuple[float, float]:
    """Mean and variance of a count distribution (dispersion diagnostics)."""
    support = np.arange(len(dist), dtype=np.float64)
    mean = float(np.sum(support * dist))
    var = float(np.sum((support - mean) ** 2 * dist))
    return mean, var
