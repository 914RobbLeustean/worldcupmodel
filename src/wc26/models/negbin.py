"""Negative-binomial (NB2) fit/predict shared by the corners and cards models.

statsmodels does the regression MLE (new dependency, DECISIONS D018);
scipy.stats supplies the pmf. NB2 parameterization throughout:
Var = mu + alpha * mu^2 — alpha is the overdispersion vs Poisson, and the
raw majors data is clearly overdispersed (corners var/mean ~1.25, cards
~1.32), which is why these are not Poisson models.

Fits are deterministic: statsmodels' MLE starts from a Poisson fit on sorted
data, no randomness involved.
"""

import numpy as np
import statsmodels.api as sm
from numpy.typing import NDArray
from scipy import stats

# Below this the NB2 is operationally Poisson (at mu=9 it adds < 0.1 to the
# variance) and the boundary breaks BFGS convergence — collapse to alpha=0.
_ALPHA_BOUNDARY = 1e-3


def select_features(
    columns: dict[str, NDArray[np.float64]],
    ordered: list[str],
    min_flag_support: int,
    flag_features: frozenset[str] = frozenset({"rivalry"}),
) -> list[str]:
    """Drop features a training slice cannot identify.

    Zero variance (e.g. ref_rate when no training row has a referee,
    qualifier before any qualifier data exists) makes the design singular;
    a sparse binary flag with under min_flag_support positive rows would get
    a noise coefficient that could blow up a live price. The fitted
    feature_names list records what survived, and prediction uses only those.
    """
    out = ["const"]
    for name in ordered:
        if name == "const":
            continue
        col = columns[name]
        if name in flag_features and float(col.sum()) < min_flag_support:
            continue
        if float(np.std(col)) < 1e-9:
            continue
        out.append(name)
    return out


def fit_nb2(
    y: NDArray[np.float64], design: NDArray[np.float64], feature_names: list[str]
) -> tuple[dict[str, float], float]:
    """MLE of an NB2 regression with log link; returns (coefficients, alpha).

    Warm-started from a Poisson GLM (the standard recipe; also makes the fit
    deterministic and robust on small slices). When the conditional
    overdispersion is ~0 the alpha MLE sits on the boundary and the
    optimizer cannot formally converge there — that is not a broken fit, it
    means the features absorbed the marginal overdispersion. In that case we
    return the Poisson solution explicitly: alpha = 0.0 (NB2 with alpha -> 0
    IS Poisson). Genuine non-convergence away from the boundary raises.
    """
    if design.shape != (len(y), len(feature_names)):
        raise ValueError(f"design {design.shape} vs {len(y)} rows x {len(feature_names)} features")
    poisson = sm.Poisson(y, design).fit(disp=0, maxiter=500)
    if not poisson.mle_retvals.get("converged", False):
        raise RuntimeError(f"Poisson warm-start did not converge (features: {feature_names})")
    model = sm.NegativeBinomial(y, design, loglike_method="nb2")
    start = np.append(np.asarray(poisson.params, dtype=np.float64), 0.05)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # boundary alpha emits ConvergenceWarning by design
        res = model.fit(start_params=start, method="bfgs", disp=0, maxiter=1000)
    params = np.asarray(res.params, dtype=np.float64)
    alpha = float(params[-1])
    converged = bool(res.mle_retvals.get("converged", False))
    if np.isfinite(alpha) and alpha < _ALPHA_BOUNDARY:
        coef = {
            name: float(v)
            for name, v in zip(feature_names, np.asarray(poisson.params), strict=True)
        }
        return coef, 0.0
    if not converged or not np.isfinite(alpha):
        raise RuntimeError(f"NB2 fit did not converge off-boundary (features: {feature_names})")
    coef = {name: float(v) for name, v in zip(feature_names, params[:-1], strict=True)}
    return coef, alpha


def nb2_distribution(mu: float, alpha: float, max_count: int) -> NDArray[np.float64]:
    """P(count = 0..max_count) for NB2(mu, alpha), renormalized over support.

    The truncation tail is negligible for sane max_count (corners < 30,
    cards < 25 in all recorded majors); renormalizing keeps log-loss math
    well-formed. alpha == 0 is the Poisson limit (see fit_nb2).
    """
    if mu <= 0 or alpha < 0:
        raise ValueError(f"need mu > 0 and alpha >= 0, got mu={mu}, alpha={alpha}")
    if alpha == 0.0:
        return poisson_distribution(mu, max_count)
    n = 1.0 / alpha
    p = n / (n + mu)
    counts = np.arange(max_count + 1)
    pmf = np.asarray(stats.nbinom.pmf(counts, n, p), dtype=np.float64)
    total = float(pmf.sum())
    if total < 0.99:
        raise ValueError(f"NB2 truncation at {max_count} loses {1 - total:.3f} mass (mu={mu:.2f})")
    return np.asarray(pmf / total, dtype=np.float64)


def poisson_distribution(mu: float, max_count: int) -> NDArray[np.float64]:
    """Poisson pmf over 0..max_count, renormalized (naive-baseline helper)."""
    if mu <= 0:
        raise ValueError(f"need mu > 0, got {mu}")
    counts = np.arange(max_count + 1)
    pmf = np.asarray(stats.poisson.pmf(counts, mu), dtype=np.float64)
    return np.asarray(pmf / pmf.sum(), dtype=np.float64)


def moment_matched_nb2(mean: float, var: float, max_count: int) -> NDArray[np.float64]:
    """NB2 (or Poisson when var <= mean) matching sample moments.

    The naive baseline for corners/cards: historical tournament mean AND
    dispersion, with no per-match features — a tougher, more honest baseline
    than a bare Poisson at the mean.
    """
    if var > mean:
        alpha = (var - mean) / mean**2
        return nb2_distribution(mean, alpha, max_count)
    return poisson_distribution(mean, max_count)
