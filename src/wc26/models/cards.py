"""Total-cards prop model (Phase 3.3): NB2 with the referee as the lead feature.

Target: total cards = yellows + reds, both teams, each card counting 1 (the
standard "total cards" book market; bookings-points markets are a different
contract and are NOT priced by this model).

Features (all known pre-kickoff):
- ref_rate: the assigned referee's career total-cards-per-match, shrunk to
  the all-ref mean — the biggest single feature. WC18 training rows have no
  recorded referee (ESPN has no officials data that far back) and sit at the
  mean, which attenuates but does not bias the coefficient.
- knockout: knockout matches run hotter (stakes) and cagier.
- rivalry: manual derby list in config/rivalries.yaml.
- foul_rate_sum: both teams' shrunk per-match fouls-committed rates, summed
  (LOO in training, like corners).

Feature dropping: a feature with (near-)zero variance in a training slice —
ref_rate at the WC22 cutoff (only refless WC18 behind it), rivalry with
fewer than props.min_flag_support positive rows — is dropped from THAT fit
and recorded in feature_names; predictions then ignore it. An NB coefficient
estimated on 2 matches is noise that could blow up a live price.

Referee unknown at predict time (assignments land ~2 days out), or known but
with no pre-cutoff history: the model falls back to the mean rate, widens
the variance by the between-referee spread propagated through the ref
coefficient (alpha_eff = alpha + (beta_ref * sigma_ref)^2, exact in the
NB2 mixture sense to first order), and flags the output ref_known=False.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from wc26.config import Settings
from wc26.models.goal_engine import git_sha
from wc26.models.negbin import fit_nb2, nb2_distribution, select_features
from wc26.models.prop_features import (
    PROPS_SCHEMA,
    is_rivalry,
    shrunk_referee_rates,
    shrunk_team_rates,
)

MAX_CARDS = 25
CARD_FEATURES = ["const", "ref_rate", "knockout", "rivalry", "foul_rate_sum", "qualifier"]


@dataclass(frozen=True)
class CardsParams:
    fitted_at: str
    git_sha: str
    data_cutoff: str
    n_matches: int
    feature_names: list[str]
    coef: dict[str, float]
    alpha: float
    ref_rates: dict[str, float]
    ref_rate_mean: float
    ref_rate_between_std: float
    team_foul_rates: dict[str, float]
    foul_rate_mean: float

    @property
    def version(self) -> str:
        return f"cards {self.data_cutoff} @{self.git_sha[:7]}"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["schema_version"] = 1
        path.write_text(json.dumps(payload, indent=1, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "CardsParams":
        raw: dict[str, Any] = json.loads(path.read_text())
        if raw.pop("schema_version") != 1:
            raise ValueError(f"{path}: unknown params schema version")
        return cls(**raw)


@dataclass(frozen=True)
class CardsPrediction:
    distribution: NDArray[np.float64]
    mu: float
    alpha_used: float
    ref_known: bool


def _loo_foul_sums(universe: pd.DataFrame, pseudo: float) -> NDArray[np.float64]:
    per_team = pd.concat(
        [
            pd.Series(
                universe["fouls_home"].to_numpy(dtype=float), index=universe["home_id"].array
            ),
            pd.Series(
                universe["fouls_away"].to_numpy(dtype=float), index=universe["away_id"].array
            ),
        ]
    )
    mean = float(per_team.mean())
    sums = per_team.groupby(level=0).sum()
    counts = per_team.groupby(level=0).count()
    out = np.empty(len(universe), dtype=np.float64)
    rows = zip(
        universe["home_id"].tolist(),
        universe["away_id"].tolist(),
        universe["fouls_home"].tolist(),
        universe["fouls_away"].tolist(),
        strict=True,
    )
    for i, (home, away, x_home, x_away) in enumerate(rows):
        loo_h = (float(sums[home]) - float(x_home) + pseudo * mean) / (
            float(counts[home]) - 1 + pseudo
        )
        loo_a = (float(sums[away]) - float(x_away) + pseudo * mean) / (
            float(counts[away]) - 1 + pseudo
        )
        out[i] = loo_h + loo_a
    return out


def _loo_ref_rates(universe: pd.DataFrame, pseudo: float) -> tuple[NDArray[np.float64], float]:
    """Per-row LOO shrunk career rate of the row's referee; mean for unknowns."""
    known = universe[universe["referee"].notna() & (universe["referee"] != "")]
    mean = (
        float(known["total_cards"].mean())
        if not known.empty
        else float(universe["total_cards"].mean())
    )
    sums = known.groupby("referee")["total_cards"].sum()
    counts = known.groupby("referee")["total_cards"].count()
    out = np.full(len(universe), mean, dtype=np.float64)
    rows = zip(universe["referee"].tolist(), universe["total_cards"].tolist(), strict=True)
    for i, (ref, cards) in enumerate(rows):
        if ref and not pd.isna(ref) and ref in sums.index:
            out[i] = (float(sums[ref]) - float(cards) + pseudo * mean) / (
                float(counts[ref]) - 1 + pseudo
            )
    return out, mean


def fit_cards(
    universe: pd.DataFrame,
    rivalries: frozenset[frozenset[str]],
    cutoff: pd.Timestamp,
    settings: Settings,
) -> CardsParams:
    """Fit the cards NB2 on a pre-cutoff universe slice (see module docstring)."""
    if (universe["date"] >= cutoff).any():
        raise ValueError(f"cards training data extends past cutoff {cutoff.date()} — leak")
    if len(universe) < settings.props.min_train_rows:
        raise ValueError(
            f"only {len(universe)} cards training rows < min {settings.props.min_train_rows} "
            f"— add fifa.worldq.* legs to espn.py TOURNAMENTS rather than lowering the bar"
        )
    universe = PROPS_SCHEMA.validate(
        universe.sort_values(["date", "home_id"], kind="stable").reset_index(drop=True)
    )
    pseudo_team = settings.props.team_rate_pseudo_matches
    pseudo_ref = settings.props.ref_rate_pseudo_matches

    ref_col, _ = _loo_ref_rates(universe, pseudo_ref)
    rivalry_col = np.array(
        [
            1.0 if is_rivalry(str(h), str(a), rivalries) else 0.0
            for h, a in zip(universe["home_id"], universe["away_id"], strict=True)
        ]
    )
    columns: dict[str, NDArray[np.float64]] = {
        "const": np.ones(len(universe), dtype=np.float64),
        "ref_rate": ref_col,
        "knockout": universe["knockout"].to_numpy(dtype=np.float64),
        "rivalry": rivalry_col,
        "foul_rate_sum": _loo_foul_sums(universe, pseudo_team),
        "qualifier": universe["qualifier"].to_numpy(dtype=np.float64),
    }
    features = select_features(columns, CARD_FEATURES, settings.props.min_flag_support)
    design = np.column_stack([columns[f] for f in features])
    y = universe["total_cards"].to_numpy(dtype=np.float64)
    coef, alpha = fit_nb2(y, design, features)

    ref_rates, ref_mean, ref_std = shrunk_referee_rates(universe, pseudo_ref)
    foul_rates, foul_mean = shrunk_team_rates(universe, "fouls_home", "fouls_away", pseudo_team)
    return CardsParams(
        fitted_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        data_cutoff=str(cutoff.date()),
        n_matches=len(universe),
        feature_names=features,
        coef=coef,
        alpha=alpha,
        ref_rates=ref_rates,
        ref_rate_mean=ref_mean,
        ref_rate_between_std=ref_std,
        team_foul_rates=foul_rates,
        foul_rate_mean=foul_mean,
    )


def latest_cards_path() -> Path:
    """Most recent saved cards model (filename-sorted, like the engine's)."""
    from wc26.models.goal_engine import MODELS_DIR

    candidates = sorted(MODELS_DIR.glob("cards_*.json"))
    if not candidates:
        raise FileNotFoundError(f"no fitted cards model under {MODELS_DIR} — run `wc26 refit`")
    return candidates[-1]


def predict_cards(
    params: CardsParams,
    home_id: str,
    away_id: str,
    referee: str | None,
    knockout: bool,
    rivalry: bool,
) -> CardsPrediction:
    """Total-cards distribution for one match; ref-unknown widens and flags.

    A referee who is named but has no pre-cutoff history prices identically
    to an unnamed one (mean rate, widened variance) and is reported as
    ref_known=False — the honest label, since the rate feature is what the
    model actually knows about a ref.
    """
    ref_known = bool(referee) and referee in params.ref_rates
    ref_rate = params.ref_rates[referee] if ref_known and referee else params.ref_rate_mean
    values = {
        "const": 1.0,
        "ref_rate": ref_rate,
        "knockout": 1.0 if knockout else 0.0,
        "rivalry": 1.0 if rivalry else 0.0,
        "foul_rate_sum": params.team_foul_rates.get(home_id, params.foul_rate_mean)
        + params.team_foul_rates.get(away_id, params.foul_rate_mean),
        # Prediction always prices finals matches (D020).
        "qualifier": 0.0,
    }
    mu = float(np.exp(sum(params.coef[f] * values[f] for f in params.feature_names)))
    alpha = params.alpha
    if not ref_known and "ref_rate" in params.feature_names:
        beta = params.coef["ref_rate"]
        alpha = alpha + (beta * params.ref_rate_between_std) ** 2
    return CardsPrediction(
        distribution=nb2_distribution(mu, alpha, MAX_CARDS),
        mu=mu,
        alpha_used=alpha,
        ref_known=ref_known,
    )
