"""Baselines the goal engine must be judged against.

Elo-only model: turns a pre-match Elo difference into 1X2 probabilities via
the standard Elo win expectancy evaluated at +/- a draw-width offset nu:

    p_home = 1 / (1 + 10 ** (-(dr - nu) / 400))
    p_away = 1 / (1 + 10 ** (-(-dr - nu) / 400))
    p_draw = 1 - p_home - p_away

with dr = elo_home - elo_away + 100 for a non-neutral home team (the same
+100 the Elo computation itself uses). nu > 0 carves the draw out of the win
expectancy symmetrically; it is fit by minimizing log-loss on the training
window (scipy scalar minimization — deterministic, refit at every walk-
forward cutoff so the baseline never sees future data either).

Market baseline: de-vigged average closing-ish odds, multiplicative method
via penaltyblog (D005 — never hand-rolled).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from penaltyblog.implied import calculate_implied
from scipy.optimize import minimize_scalar

from wc26.backtest.metrics import log_loss

ELO_HOME_ADV = 100.0


def _elo_probs(dr: NDArray[np.float64], nu: float) -> NDArray[np.float64]:
    p_home = 1.0 / (1.0 + 10.0 ** (-(dr - nu) / 400.0))
    p_away = 1.0 / (1.0 + 10.0 ** (-(-dr - nu) / 400.0))
    p_draw = np.clip(1.0 - p_home - p_away, 1e-9, None)
    probs = np.stack([p_home, p_draw, p_away], axis=1)
    total: NDArray[np.float64] = probs.sum(axis=1, keepdims=True)
    return probs / total


@dataclass(frozen=True)
class EloBaseline:
    """1X2 from Elo difference with a fitted draw width."""

    nu: float

    def predict(
        self,
        elo_home: NDArray[np.float64],
        elo_away: NDArray[np.float64],
        neutral: NDArray[np.bool_],
    ) -> NDArray[np.float64]:
        dr = elo_home - elo_away + np.where(neutral, 0.0, ELO_HOME_ADV)
        return _elo_probs(dr.astype(np.float64), self.nu)


def fit_elo_baseline(
    elo_home: NDArray[np.float64],
    elo_away: NDArray[np.float64],
    neutral: NDArray[np.bool_],
    outcomes: NDArray[np.int64],
) -> EloBaseline:
    """Fit the draw width nu by maximum likelihood on training matches."""
    dr = (elo_home - elo_away + np.where(neutral, 0.0, ELO_HOME_ADV)).astype(np.float64)

    def neg_ll(nu: float) -> float:
        return log_loss(_elo_probs(dr, nu), outcomes)

    res = minimize_scalar(neg_ll, bounds=(1.0, 400.0), method="bounded")
    if not res.success:
        raise RuntimeError(f"Elo draw-width fit failed: {res.message}")
    return EloBaseline(nu=float(res.x))


def devig_1x2(odds: NDArray[np.float64]) -> NDArray[np.float64]:
    """De-vig rows of decimal [home, draw, away] odds (multiplicative, D005)."""
    if odds.ndim != 2 or odds.shape[1] != 3:
        raise ValueError(f"odds must be (n, 3), got {odds.shape}")
    out = np.empty_like(odds, dtype=np.float64)
    for i, row in enumerate(odds):
        out[i] = calculate_implied(
            [float(row[0]), float(row[1]), float(row[2])], method="multiplicative"
        ).probabilities
    return out
