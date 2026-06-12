"""Total-corners prop model (Phase 3.2): NB2 regression on engine + rate features.

Features per match (all known pre-kickoff, walk-forward safe):
- xg_gap: |home - away| goal expectation from the goal engine fitted at the
  same cutoff — mismatched games funnel one team into the corner-generating
  siege pattern.
- fav_prob: the favorite's 90' win probability from the same grid (the
  "favorite status" in the spec; correlated with xg_gap but not identical —
  it also sees the draw mass).
- shots_sum: both teams' shrunk per-match shots-taken rates, summed (attack
  volume proxy).
- corner_rate_sum: both teams' shrunk per-match corners-taken rates, summed.
- md3 / knockout: stage dummies vs the MD1/MD2 baseline (MD3 rotation/dead
  rubbers, knockout cagedness).

Training-row rates are leave-one-out (a match must not see its own corners
in its team-rate feature — with 3-7 prior matches per team at the WC22
cutoff the contamination would be material); prediction uses the full
shrunk rates stored in the params. ET rows are excluded upstream (D017).
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
from wc26.models.goal_engine import GoalEngineParams, git_sha, predict_grid
from wc26.models.negbin import fit_nb2, nb2_distribution, select_features
from wc26.models.prop_features import PROPS_SCHEMA, shrunk_team_rates

MAX_CORNERS = 30
CORNER_FEATURES = [
    "const",
    "xg_gap",
    "fav_prob",
    "shots_sum",
    "corner_rate_sum",
    "md3",
    "knockout",
    "qualifier",
]


@dataclass(frozen=True)
class CornersParams:
    fitted_at: str
    git_sha: str
    data_cutoff: str
    n_matches: int
    goal_engine_version: str
    feature_names: list[str]
    coef: dict[str, float]
    alpha: float
    team_corner_rates: dict[str, float]
    corner_rate_mean: float
    team_shot_rates: dict[str, float]
    shot_rate_mean: float

    @property
    def version(self) -> str:
        return f"corners {self.data_cutoff} @{self.git_sha[:7]}"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["schema_version"] = 1
        path.write_text(json.dumps(payload, indent=1, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "CornersParams":
        raw: dict[str, Any] = json.loads(path.read_text())
        if raw.pop("schema_version") != 1:
            raise ValueError(f"{path}: unknown params schema version")
        return cls(**raw)


def _engine_features(
    engine: GoalEngineParams, home_id: str, away_id: str, neutral: bool
) -> tuple[float, float]:
    """(xg_gap, fav_prob) from the goal engine grid."""
    grid = predict_grid(engine, home_id, away_id, neutral)
    p_home, _, p_away = (float(p) for p in grid.home_draw_away)
    xg_gap = abs(float(grid.home_goal_expectation) - float(grid.away_goal_expectation))
    return xg_gap, max(p_home, p_away)


def _loo_rate_sums(
    universe: pd.DataFrame, home_col: str, away_col: str, pseudo: float
) -> NDArray[np.float64]:
    """Per-row sum of both teams' leave-one-out shrunk rates of a stat."""
    per_team = pd.concat(
        [
            pd.Series(universe[home_col].to_numpy(dtype=float), index=universe["home_id"].array),
            pd.Series(universe[away_col].to_numpy(dtype=float), index=universe["away_id"].array),
        ]
    )
    mean = float(per_team.mean())
    sums = per_team.groupby(level=0).sum()
    counts = per_team.groupby(level=0).count()

    def loo(team: str, own: float) -> float:
        return (float(sums[team]) - own + pseudo * mean) / (float(counts[team]) - 1 + pseudo)

    out = np.empty(len(universe), dtype=np.float64)
    rows = zip(
        universe["home_id"].tolist(),
        universe["away_id"].tolist(),
        universe[home_col].tolist(),
        universe[away_col].tolist(),
        strict=True,
    )
    for i, (home, away, x_home, x_away) in enumerate(rows):
        out[i] = loo(str(home), float(x_home)) + loo(str(away), float(x_away))
    return out


def build_corners_columns(
    universe: pd.DataFrame, engine: GoalEngineParams, settings: Settings
) -> dict[str, NDArray[np.float64]]:
    """Training feature columns (LOO rate features; see module docstring)."""
    universe = PROPS_SCHEMA.validate(universe)
    pseudo = settings.props.team_rate_pseudo_matches
    eng = [
        _engine_features(engine, str(h), str(a), bool(nt))
        for h, a, nt in zip(
            universe["home_id"], universe["away_id"], universe["neutral"], strict=True
        )
    ]
    return {
        "const": np.ones(len(universe), dtype=np.float64),
        "xg_gap": np.array([e[0] for e in eng], dtype=np.float64),
        "fav_prob": np.array([e[1] for e in eng], dtype=np.float64),
        "shots_sum": _loo_rate_sums(universe, "shots_home", "shots_away", pseudo),
        "corner_rate_sum": _loo_rate_sums(universe, "corners_home", "corners_away", pseudo),
        "md3": (universe["matchday"] == 3).to_numpy(dtype=np.float64),
        "knockout": universe["knockout"].to_numpy(dtype=np.float64),
        "qualifier": universe["qualifier"].to_numpy(dtype=np.float64),
    }


def fit_corners(
    universe: pd.DataFrame,
    engine: GoalEngineParams,
    cutoff: pd.Timestamp,
    settings: Settings,
) -> CornersParams:
    """Fit the corners NB2 on a pre-cutoff universe slice.

    `universe` must already be strictly before `cutoff` (the props harness
    and refit both slice before calling); raises if not, because a leak here
    silently prices bad lines.
    """
    if (universe["date"] >= cutoff).any():
        raise ValueError(f"corners training data extends past cutoff {cutoff.date()} — leak")
    if len(universe) < settings.props.min_train_rows:
        raise ValueError(
            f"only {len(universe)} corners training rows < min {settings.props.min_train_rows} "
            f"— add fifa.worldq.* legs to espn.py TOURNAMENTS rather than lowering the bar"
        )
    universe = universe.sort_values(["date", "home_id"], kind="stable").reset_index(drop=True)
    columns = build_corners_columns(universe, engine, settings)
    features = select_features(columns, CORNER_FEATURES, settings.props.min_flag_support)
    design = np.column_stack([columns[f] for f in features])
    y = universe["total_corners"].to_numpy(dtype=np.float64)
    coef, alpha = fit_nb2(y, design, features)

    pseudo = settings.props.team_rate_pseudo_matches
    corner_rates, corner_mean = shrunk_team_rates(universe, "corners_home", "corners_away", pseudo)
    shot_rates, shot_mean = shrunk_team_rates(universe, "shots_home", "shots_away", pseudo)
    return CornersParams(
        fitted_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        data_cutoff=str(cutoff.date()),
        n_matches=len(universe),
        goal_engine_version=engine.version,
        feature_names=features,
        coef=coef,
        alpha=alpha,
        team_corner_rates=corner_rates,
        corner_rate_mean=corner_mean,
        team_shot_rates=shot_rates,
        shot_rate_mean=shot_mean,
    )


def latest_corners_path() -> Path:
    """Most recent saved corners model (cutoff + fit time, like the engine's)."""
    from wc26.models.goal_engine import latest_model_path

    return latest_model_path("corners")


def predict_corners(
    params: CornersParams,
    engine: GoalEngineParams,
    home_id: str,
    away_id: str,
    neutral: bool,
    matchday: int,
    knockout: bool,
) -> NDArray[np.float64]:
    """Total-corners distribution P(0..MAX_CORNERS) for one match.

    Teams unseen in the majors training sample (debutants) fall back to the
    league-mean rates; the engine features still differentiate them.
    """
    xg_gap, fav_prob = _engine_features(engine, home_id, away_id, neutral)
    shots_sum = params.team_shot_rates.get(home_id, params.shot_rate_mean) + (
        params.team_shot_rates.get(away_id, params.shot_rate_mean)
    )
    corner_sum = params.team_corner_rates.get(home_id, params.corner_rate_mean) + (
        params.team_corner_rates.get(away_id, params.corner_rate_mean)
    )
    values = {
        "const": 1.0,
        "xg_gap": xg_gap,
        "fav_prob": fav_prob,
        "shots_sum": shots_sum,
        "corner_rate_sum": corner_sum,
        "md3": 1.0 if matchday == 3 else 0.0,
        "knockout": 1.0 if knockout else 0.0,
        # Prediction always prices finals matches; qualifiers are a
        # training-only level dummy (D020).
        "qualifier": 0.0,
    }
    mu = float(np.exp(sum(params.coef[f] * values[f] for f in params.feature_names)))
    return nb2_distribution(mu, params.alpha, MAX_CORNERS)
