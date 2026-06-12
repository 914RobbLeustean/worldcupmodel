"""Scoring rules for 3-way (1X2) probabilistic predictions.

Plain definitions, no fitting — log-loss and Brier are not in the
"never hand-roll" set (that covers Poisson likelihoods and de-vig math).
Outcome encoding everywhere: 0 = home win, 1 = draw, 2 = away win (90').
"""

import numpy as np
from numpy.typing import NDArray

_EPS = 1e-12


def _check(probs: NDArray[np.float64], outcomes: NDArray[np.int64]) -> None:
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError(f"probs must be (n, 3), got {probs.shape}")
    if probs.shape[0] != outcomes.shape[0]:
        raise ValueError("probs and outcomes length mismatch")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("probability rows must sum to 1")
    if outcomes.min() < 0 or outcomes.max() > 2:
        raise ValueError("outcomes must be in {0, 1, 2}")


def log_loss(probs: NDArray[np.float64], outcomes: NDArray[np.int64]) -> float:
    """Mean negative log probability of the realized outcome (nats)."""
    _check(probs, outcomes)
    picked = probs[np.arange(len(outcomes)), outcomes]
    return float(-np.mean(np.log(np.clip(picked, _EPS, None))))


def brier(probs: NDArray[np.float64], outcomes: NDArray[np.int64]) -> float:
    """Multiclass Brier score: mean squared distance to the outcome one-hot."""
    _check(probs, outcomes)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(outcomes)), outcomes] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
