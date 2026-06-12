"""NB2 machinery: parameter recovery, Poisson boundary, feature selection."""

import numpy as np
import pytest
from scipy import stats

from wc26.models.negbin import (
    fit_nb2,
    moment_matched_nb2,
    nb2_distribution,
    poisson_distribution,
    select_features,
)


def _synthetic(alpha: float, n: int = 2000, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    design = np.column_stack([np.ones(n), x])
    mu = np.exp(2.0 + 0.3 * x)
    if alpha > 0:
        shape = 1.0 / alpha
        lam = rng.gamma(shape, mu / shape)
    else:
        lam = mu
    y = rng.poisson(lam).astype(np.float64)
    return y, design


def test_fit_nb2_recovers_parameters() -> None:
    y, design = _synthetic(alpha=0.15)
    coef, alpha = fit_nb2(y, design, ["const", "x"])
    assert coef["const"] == pytest.approx(2.0, abs=0.05)
    assert coef["x"] == pytest.approx(0.3, abs=0.05)
    assert alpha == pytest.approx(0.15, abs=0.05)


def test_fit_nb2_poisson_data_returns_alpha_zero() -> None:
    y, design = _synthetic(alpha=0.0)
    coef, alpha = fit_nb2(y, design, ["const", "x"])
    assert alpha == 0.0
    assert coef["const"] == pytest.approx(2.0, abs=0.05)


def test_fit_nb2_is_deterministic() -> None:
    y, design = _synthetic(alpha=0.15)
    first = fit_nb2(y, design, ["const", "x"])
    second = fit_nb2(y, design, ["const", "x"])
    assert first == second


def test_nb2_distribution_moments() -> None:
    dist = nb2_distribution(mu=9.0, alpha=0.05, max_count=40)
    assert dist.sum() == pytest.approx(1.0)
    mean = float(np.sum(np.arange(41) * dist))
    var = float(np.sum((np.arange(41) - mean) ** 2 * dist))
    assert mean == pytest.approx(9.0, rel=1e-3)
    assert var == pytest.approx(9.0 + 0.05 * 81.0, rel=1e-2)


def test_nb2_alpha_zero_is_poisson() -> None:
    assert nb2_distribution(3.5, 0.0, 20) == pytest.approx(poisson_distribution(3.5, 20))
    expected = stats.poisson.pmf(np.arange(21), 3.5)
    assert poisson_distribution(3.5, 20) == pytest.approx(expected / expected.sum())


def test_moment_matched_nb2_matches_sample_moments() -> None:
    dist = moment_matched_nb2(mean=9.2, var=11.4, max_count=50)
    mean = float(np.sum(np.arange(51) * dist))
    var = float(np.sum((np.arange(51) - mean) ** 2 * dist))
    assert mean == pytest.approx(9.2, rel=1e-3)
    assert var == pytest.approx(11.4, rel=1e-2)


def test_moment_matched_underdispersed_falls_back_to_poisson() -> None:
    assert moment_matched_nb2(4.0, 3.0, 20) == pytest.approx(poisson_distribution(4.0, 20))


def test_select_features_drops_degenerate_columns() -> None:
    n = 50
    columns = {
        "const": np.ones(n),
        "good": np.linspace(0, 1, n),
        "flat": np.full(n, 2.5),
        "rivalry": np.zeros(n),
    }
    columns["rivalry"][:3] = 1.0  # only 3 positives < min support 5
    kept = select_features(columns, ["const", "good", "flat", "rivalry"], min_flag_support=5)
    assert kept == ["const", "good"]
