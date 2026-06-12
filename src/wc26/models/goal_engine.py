"""Dixon-Coles goal engine with Elo-anchored shrinkage (Phase 2).

Fit pipeline (all math through penaltyblog — never hand-rolled):
1. Training rows: internationals inside a sliding window before the cutoff,
   minus extra-time-contaminated rows (D012/D014). Weight per match =
   exp(-decay * days_before_cutoff) * tier_weight (settings.yaml).
2. penaltyblog DixonColesGoalModel fit with per-match neutral-venue flags —
   home advantage is only learned from (and only applied to) true home games.
3. Elo-anchored shrinkage (small-data humility invariant): attack/defence are
   regressed on as-of-cutoff Elo across well-sampled teams, then every team's
   parameters are blended toward that regression line:
       blended = w * fitted + (1 - w) * anchor(elo),  w = n_eff / (n_eff + n0)
   where n_eff is the team's total fit weight. A debutant (n_eff ~ 0) is
   priced off its Elo; an ever-present team keeps its fitted strengths.
   Exact constants live in settings.yaml; rationale in docs/MODEL.md.

Prediction composes lambdas from blended params and goes through
penaltyblog's create_dixon_coles_grid, so backtest and live predictions share
one code path. All outputs are 90-minute probabilities (D004).
"""

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa
from penaltyblog.models import (
    DixonColesGoalModel,
    FootballProbabilityGrid,
    create_dixon_coles_grid,
    dixon_coles_weights,
)

from wc26.config import REPO_ROOT, Settings
from wc26.data.results import RESULTS_SCHEMA

MODELS_DIR = REPO_ROOT / "data" / "processed" / "models"

TRAIN_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "home_score": pa.Column(int, pa.Check.ge(0)),
        "away_score": pa.Column(int, pa.Check.ge(0)),
        "tier": pa.Column(
            str, pa.Check.isin(["world_cup", "continental", "qualifier", "friendly"])
        ),
        "neutral": pa.Column(bool),
    },
    strict="filter",
    coerce=True,
)


def prepare_training_data(
    results: pd.DataFrame,
    match_stats: pd.DataFrame,
    cutoff: pd.Timestamp,
    window_years: int,
) -> pd.DataFrame:
    """Training slice: window before cutoff, extra-time rows removed (D012).

    `match_stats` carries per-event extra_time flags for 2018+ majors (incl.
    WC26 live). Flagged matches are matched back to results by team pair
    within ±1 day (D013) and dropped: their stored scores include extra time,
    which would corrupt a 90-minute model. Pre-2018 contamination is accepted
    and documented (D014).
    """
    results = RESULTS_SCHEMA.validate(results)
    window = results[
        (results["date"] < cutoff) & (results["date"] >= cutoff - pd.DateOffset(years=window_years))
    ].reset_index(drop=True)

    et = match_stats[match_stats["extra_time"].astype(bool)]
    drop = pd.Series(False, index=window.index)
    et_cols = zip(et["date"].tolist(), et["home_id"].tolist(), et["away_id"].tolist(), strict=True)
    for et_date, et_home, et_away in et_cols:
        pair_match = ((window["home_id"] == et_home) & (window["away_id"] == et_away)) | (
            (window["home_id"] == et_away) & (window["away_id"] == et_home)
        )
        close_date = (window["date"] - pd.Timestamp(et_date)).abs() <= pd.Timedelta(days=1)
        drop |= pair_match & close_date
    return TRAIN_SCHEMA.validate(window[~drop].reset_index(drop=True))


@dataclass(frozen=True)
class TeamStrength:
    attack: float
    defence: float
    eff_matches: float


@dataclass(frozen=True)
class GoalEngineParams:
    fitted_at: str
    git_sha: str
    data_cutoff: str
    n_matches: int
    decay_xi: float
    tier_weights: dict[str, float]
    anchor_pseudo_matches: float
    home_advantage: float
    rho: float
    anchor_attack: tuple[float, float]  # (intercept, slope per Elo point)
    anchor_defence: tuple[float, float]
    teams: dict[str, TeamStrength]

    @property
    def version(self) -> str:
        return f"goal_engine {self.data_cutoff} @{self.git_sha[:7]}"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["schema_version"] = 1
        path.write_text(json.dumps(payload, indent=1, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "GoalEngineParams":
        raw: dict[str, Any] = json.loads(path.read_text())
        if raw.pop("schema_version") != 1:
            raise ValueError(f"{path}: unknown params schema version")
        raw["teams"] = {tid: TeamStrength(**ts) for tid, ts in raw["teams"].items()}
        raw["anchor_attack"] = tuple(raw["anchor_attack"])
        raw["anchor_defence"] = tuple(raw["anchor_defence"])
        return cls(**raw)


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def fit_goal_engine(
    train: pd.DataFrame,
    elo_ratings: pd.Series,
    cutoff: pd.Timestamp,
    settings: Settings,
) -> GoalEngineParams:
    """Fit Dixon-Coles on a prepared training slice and blend with Elo.

    `elo_ratings` must be ratings_asof(cutoff) — using anything later leaks.
    Deterministic: penaltyblog's MLE has no random component and the data is
    sorted before fitting.
    """
    train = TRAIN_SCHEMA.validate(train).sort_values(["date", "home_id"], kind="stable")
    ge = settings.goal_engine

    decay = np.asarray(
        dixon_coles_weights(train["date"], xi=settings.dixon_coles_decay, base_date=cutoff),
        dtype=np.float64,
    )
    tier_w = train["tier"].map(ge.tier_weights).to_numpy(dtype=np.float64)
    weights = np.ascontiguousarray(decay * tier_w)

    # penaltyblog's Cython loss needs writable buffers; pandas 3 hands out
    # read-only views, so copy explicitly.
    model = DixonColesGoalModel(
        train["home_score"].to_numpy(dtype=np.int64).copy(),
        train["away_score"].to_numpy(dtype=np.int64).copy(),
        np.asarray(train["home_id"].tolist()),
        np.asarray(train["away_id"].tolist()),
        weights=weights,
        neutral_venue=train["neutral"].to_numpy(dtype=np.int64).copy(),
    )
    model.fit()
    fitted: dict[str, float] = {k: float(v) for k, v in model.get_params().items()}

    eff = (
        pd.concat(
            [
                pd.Series(weights, index=train["home_id"].tolist()),
                pd.Series(weights, index=train["away_id"].tolist()),
            ]
        )
        .groupby(level=0)
        .sum()
    )

    trained = sorted({t for t in eff.index if f"attack_{t}" in fitted})
    anchor_teams = [
        t for t in trained if eff[t] >= ge.elo_anchor_min_effective_matches and t in elo_ratings
    ]
    if len(anchor_teams) < 20:
        raise ValueError(
            f"only {len(anchor_teams)} teams qualify for the Elo anchor regression — "
            f"training window too small to anchor safely"
        )
    elo_x = np.array([float(elo_ratings[t]) for t in anchor_teams])
    att_y = np.array([fitted[f"attack_{t}"] for t in anchor_teams])
    def_y = np.array([fitted[f"defence_{t}"] for t in anchor_teams])
    att_slope, att_icept = (float(v) for v in np.polyfit(elo_x, att_y, deg=1))
    def_slope, def_icept = (float(v) for v in np.polyfit(elo_x, def_y, deg=1))

    n0 = ge.elo_anchor_pseudo_matches
    teams: dict[str, TeamStrength] = {}
    for team in sorted(set(trained) | set(elo_ratings.index)):
        if team not in elo_ratings:
            # Trained but unrated can't happen (Elo covers every played match);
            # guard anyway rather than silently anchoring to nothing.
            raise ValueError(f"team {team!r} has matches but no Elo rating as of {cutoff.date()}")
        elo = float(elo_ratings[team])
        prior_att = att_icept + att_slope * elo
        prior_def = def_icept + def_slope * elo
        n_eff = float(eff.get(team, 0.0)) if team in trained else 0.0
        w = n_eff / (n_eff + n0)
        teams[team] = TeamStrength(
            attack=w * fitted.get(f"attack_{team}", 0.0) + (1 - w) * prior_att,
            defence=w * fitted.get(f"defence_{team}", 0.0) + (1 - w) * prior_def,
            eff_matches=round(n_eff, 3),
        )

    return GoalEngineParams(
        fitted_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        data_cutoff=str(cutoff.date()),
        n_matches=len(train),
        decay_xi=settings.dixon_coles_decay,
        tier_weights=dict(ge.tier_weights),
        anchor_pseudo_matches=n0,
        home_advantage=fitted["home_advantage"],
        rho=fitted["rho"],
        anchor_attack=(att_icept, att_slope),
        anchor_defence=(def_icept, def_slope),
        teams=teams,
    )


def predict_grid(
    params: GoalEngineParams,
    home_id: str,
    away_id: str,
    neutral: bool,
    max_goals: int = 15,
) -> FootballProbabilityGrid:
    """Full correct-score grid for one match (90 minutes, D004).

    Home advantage applies only when neutral=False — at WC26 that is host
    nations only (the fixtures table carries the flag).
    """
    for team in (home_id, away_id):
        if team not in params.teams:
            raise KeyError(
                f"team {team!r} not in fitted params (cutoff {params.data_cutoff}) — "
                f"unknown to both training data and Elo"
            )
    home, away = params.teams[home_id], params.teams[away_id]
    ha = 0.0 if neutral else params.home_advantage
    lam_home = float(np.exp(home.attack + away.defence + ha))
    lam_away = float(np.exp(away.attack + home.defence))
    grid: FootballProbabilityGrid = create_dixon_coles_grid(
        lam_home, lam_away, rho=params.rho, max_goals=max_goals
    )
    return grid


def latest_model_path(prefix: str) -> Path:
    """Most recent saved model `<prefix>_<cutoff>_<sha>.json`.

    Ordered by (data_cutoff, fitted_at) read from the payload — two same-day
    refits share a cutoff and a pure filename sort would tie-break on the
    git SHA, which is meaningless.
    """
    candidates = list(MODELS_DIR.glob(f"{prefix}_*.json"))
    if not candidates:
        raise FileNotFoundError(f"no fitted {prefix} under {MODELS_DIR} — run `wc26 refit`")

    def key(path: Path) -> tuple[str, str]:
        raw: dict[str, Any] = json.loads(path.read_text())
        return (str(raw["data_cutoff"]), str(raw["fitted_at"]))

    return max(candidates, key=key)


def latest_params_path() -> Path:
    """Most recent saved goal engine params."""
    return latest_model_path("goal_engine")
