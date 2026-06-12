"""Walk-forward backtest for the Phase 3 prop models (PLAN 3.4).

Reuses the Phase 2 leakage discipline: monthly refit cutoffs over the
2018→2024 majors; every prediction comes from models fit on data strictly
before its cutoff ≤ match date. Three markets:

- Team/match totals: marginals of the goal engine grid (models/team_totals).
  Evaluated at every cutoff (the engine trains on the full results history).
  This run is also where the Phase 2 "totals look under-dispersed" flag is
  quantified: predicted-vs-residual variance ratio and calibration slopes
  land in the summary (docs/MODEL.md + D019).
- Corners / cards: NB2 models, fit per cutoff once at least
  props.min_train_rows non-ET majors rows exist — in practice WC18 is
  training-only and their eval sample starts at WC22.

Naive baselines (the PLAN 3.4 gate): historical tournament mean for the
stat, walk-forward — Poisson at the pre-cutoff majors scoring mean for
totals; moment-matched NB2 (mean AND dispersion, tougher than bare Poisson)
on pre-cutoff majors for corners/cards.

Extra time: ET rows are excluded from training and evaluation (D017) — their
stat totals include ET and the 90' split is unrecoverable. Evaluation
outcomes here are therefore true 90-minute counts.

Artifacts under data/processed/backtest/ — `wc26 backtest` refreshes them,
tests/test_prop_gates.py asserts on them.
"""

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from wc26.backtest.harness import BACKTEST_DIR
from wc26.backtest.metrics import binary_log_loss, calibration_slope
from wc26.config import Settings
from wc26.data.elo import compute_elo_history
from wc26.models.cards import fit_cards, predict_cards
from wc26.models.corners import fit_corners, predict_corners
from wc26.models.goal_engine import (
    GoalEngineParams,
    fit_goal_engine,
    git_sha,
    predict_grid,
    prepare_training_data,
)
from wc26.models.negbin import moment_matched_nb2, poisson_distribution
from wc26.models.prop_features import is_rivalry, load_rivalries, props_universe
from wc26.models.team_totals import (
    distribution_mean_var,
    goal_marginals,
    p_over,
    total_distribution,
)

TOTALS_PARQUET = BACKTEST_DIR / "props_totals_backtest.parquet"
CORNERS_PARQUET = BACKTEST_DIR / "props_corners_backtest.parquet"
CARDS_PARQUET = BACKTEST_DIR / "props_cards_backtest.parquet"
PROPS_SUMMARY_JSON = BACKTEST_DIR / "props_summary.json"

TEAM_GOAL_LINES = (0.5, 1.5, 2.5)
MATCH_GOAL_LINES = (1.5, 2.5, 3.5)
CORNER_LINES = (7.5, 8.5, 9.5, 10.5, 11.5)
CARD_LINES = (2.5, 3.5, 4.5, 5.5)
# Canonical lines for the calibration-slope gates: nearest half-line to the
# sample mean of each stat (team goals ~1.25, match goals ~2.5, corners
# ~9.2, cards ~3.7) — maximizes outcome variance, i.e. statistical power.
CANONICAL_TEAM_LINE = 1.5
CANONICAL_MATCH_LINE = 2.5
CANONICAL_CORNER_LINE = 9.5
CANONICAL_CARD_LINE = 3.5

NAIVE_GOALS_WINDOW_YEARS = 20


def _monthly_cutoffs(dates: pd.Series) -> list[pd.Timestamp]:
    return [pd.Timestamp(c) for c in sorted(dates.dt.to_period("M").dt.start_time.unique())]


def _naive_goal_means(results: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[float, float]:
    """(home, away) per-side scoring means over pre-cutoff majors.

    20-year window so the naive baseline reflects the modern game, not the
    1954 World Cup. Pre-2018 ET contamination accepted as in D014 (~0.3% of
    rows). Listed-home vs listed-away kept separate: even on neutral venues
    the seeded/administrative home side scores slightly more.
    """
    majors = results[
        results["tier"].isin(["world_cup", "continental"])
        & (results["date"] < cutoff)
        & (results["date"] >= cutoff - pd.DateOffset(years=NAIVE_GOALS_WINDOW_YEARS))
    ]
    if len(majors) < 100:
        raise ValueError(f"only {len(majors)} pre-cutoff majors for the naive totals baseline")
    return float(majors["home_score"].mean()), float(majors["away_score"].mean())


def run_props_backtest(
    settings: Settings,
    results: pd.DataFrame,
    match_stats: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Walk-forward evaluation of all three prop models on the 2018→2024 majors."""
    universe = props_universe(
        match_stats[match_stats["date"] < pd.Timestamp("2026-01-01")], results
    )
    # Qualifier rows (D020) are training-only: the gates are defined on the
    # 2018→2024 finals sample, and qualifier lines are not what we price.
    majors = universe[~universe["qualifier"]]
    rivalries = load_rivalries()
    elo_history = compute_elo_history(results, settings.elo_k)

    totals_rows: list[dict[str, Any]] = []
    corners_rows: list[dict[str, Any]] = []
    cards_rows: list[dict[str, Any]] = []
    skipped_cutoffs: list[str] = []

    for cutoff in _monthly_cutoffs(majors["date"]):
        in_month = majors[
            (majors["date"] >= cutoff) & (majors["date"] < cutoff + pd.DateOffset(months=1))
        ]
        if in_month.empty:
            continue

        train_results = prepare_training_data(
            results, match_stats, cutoff, settings.goal_engine.training_window_years
        )
        elo_asof = (
            elo_history[elo_history["date"] < cutoff].groupby("team_id")["rating_after"].last()
        )
        engine = fit_goal_engine(train_results, elo_asof, cutoff, settings)
        naive_home_mu, naive_away_mu = _naive_goal_means(results, cutoff)

        train_universe = universe[universe["date"] < cutoff]
        train_majors = majors[majors["date"] < cutoff]
        prop_models = None
        if len(train_universe) >= settings.props.min_train_rows and len(train_majors) >= 30:
            # Naive baselines use finals rows only: "historical tournament
            # mean" means the environment we price, not qualifiers.
            prop_models = (
                fit_corners(train_universe, engine, cutoff, settings),
                fit_cards(train_universe, rivalries, cutoff, settings),
                moment_matched_nb2(
                    float(train_majors["total_corners"].mean()),
                    float(train_majors["total_corners"].var(ddof=1)),
                    60,
                ),
                moment_matched_nb2(
                    float(train_majors["total_cards"].mean()),
                    float(train_majors["total_cards"].var(ddof=1)),
                    60,
                ),
            )
        else:
            skipped_cutoffs.append(str(cutoff.date()))

        for row in in_month.itertuples(index=False):
            home, away = str(row.home_id), str(row.away_id)
            neutral = bool(row.neutral)
            base = {
                "date": pd.Timestamp(str(row.date)),
                "tournament": str(row.tournament),
                "home_id": home,
                "away_id": away,
                "cutoff": cutoff,
            }
            totals_rows.append(
                base | _totals_eval(engine, row, neutral, naive_home_mu, naive_away_mu)
            )
            if prop_models is None:
                continue
            corners_params, cards_params, naive_corners, naive_cards = prop_models
            corners_dist = predict_corners(
                corners_params,
                engine,
                home,
                away,
                neutral,
                int(str(row.matchday)),
                bool(row.knockout),
            )
            corners_rows.append(
                base
                | _count_eval(
                    corners_dist,
                    naive_corners,
                    int(str(row.total_corners)),
                    CORNER_LINES,
                    "corners",
                )
            )
            referee = str(row.referee) if row.referee and not pd.isna(row.referee) else None
            rivalry = is_rivalry(home, away, rivalries)
            cards_pred = predict_cards(
                cards_params, home, away, referee, bool(row.knockout), rivalry
            )
            cards_rows.append(
                base
                | _count_eval(
                    cards_pred.distribution,
                    naive_cards,
                    int(str(row.total_cards)),
                    CARD_LINES,
                    "cards",
                )
                | {"ref_known": cards_pred.ref_known, "rivalry": rivalry}
            )

    totals_df = pd.DataFrame(totals_rows).sort_values("date").reset_index(drop=True)
    corners_df = pd.DataFrame(corners_rows).sort_values("date").reset_index(drop=True)
    cards_df = pd.DataFrame(cards_rows).sort_values("date").reset_index(drop=True)
    summary = summarize_props(totals_df, corners_df, cards_df, skipped_cutoffs, settings)
    return totals_df, corners_df, cards_df, summary


def _totals_eval(
    engine: GoalEngineParams,
    row: Any,
    neutral: bool,
    naive_home_mu: float,
    naive_away_mu: float,
) -> dict[str, Any]:
    grid = predict_grid(engine, str(row.home_id), str(row.away_id), neutral)
    home_dist, away_dist = goal_marginals(grid)
    total_dist = total_distribution(grid)
    naive_home = poisson_distribution(naive_home_mu, len(home_dist) - 1)
    naive_away = poisson_distribution(naive_away_mu, len(away_dist) - 1)
    naive_total = poisson_distribution(naive_home_mu + naive_away_mu, len(total_dist) - 1)

    hg, ag = int(row.home_score), int(row.away_score)
    out: dict[str, Any] = {"home_goals": hg, "away_goals": ag, "total_goals": hg + ag}
    for side, dist, naive in (
        ("home", home_dist, naive_home),
        ("away", away_dist, naive_away),
    ):
        for line in TEAM_GOAL_LINES:
            out[f"p_{side}_o{_tag(line)}"] = p_over(dist, line)
            out[f"naive_p_{side}_o{_tag(line)}"] = p_over(naive, line)
    for line in MATCH_GOAL_LINES:
        out[f"p_match_o{_tag(line)}"] = p_over(total_dist, line)
        out[f"naive_p_match_o{_tag(line)}"] = p_over(naive_total, line)
    out["logp_home"] = float(np.log(home_dist[hg]))
    out["logp_away"] = float(np.log(away_dist[ag]))
    out["logp_total"] = float(np.log(total_dist[hg + ag]))
    out["naive_logp_home"] = float(np.log(naive_home[hg]))
    out["naive_logp_away"] = float(np.log(naive_away[ag]))
    out["naive_logp_total"] = float(np.log(naive_total[hg + ag]))
    for name, dist in (("home", home_dist), ("away", away_dist), ("total", total_dist)):
        mean, var = distribution_mean_var(dist)
        out[f"pred_mean_{name}"] = mean
        out[f"pred_var_{name}"] = var
    return out


def _count_eval(
    dist: Any, naive: Any, realized: int, lines: tuple[float, ...], market: str
) -> dict[str, Any]:
    dist = np.asarray(dist, dtype=np.float64)
    naive = np.asarray(naive, dtype=np.float64)
    if realized >= len(dist):
        raise ValueError(f"{market}: realized count {realized} beyond distribution support")
    mean, var = distribution_mean_var(dist)
    naive_mean, naive_var = distribution_mean_var(naive)
    out: dict[str, Any] = {
        "realized": realized,
        "pred_mean": mean,
        "pred_var": var,
        "naive_mean": naive_mean,
        "naive_var": naive_var,
        "logp": float(np.log(dist[realized])),
        "naive_logp": float(np.log(naive[min(realized, len(naive) - 1)])),
    }
    for line in lines:
        out[f"p_o{_tag(line)}"] = p_over(dist, line)
        out[f"naive_p_o{_tag(line)}"] = p_over(naive, line)
    return out


def _tag(line: float) -> str:
    return f"{line:.1f}".replace(".", "")


def _binary_block(
    p: "np.typing.NDArray[np.float64]",
    naive_p: "np.typing.NDArray[np.float64]",
    hits: "np.typing.NDArray[np.bool_]",
) -> dict[str, float]:
    return {
        "n": len(hits),
        "hit_rate": float(hits.mean()),
        "mean_p": float(p.mean()),
        "log_loss": binary_log_loss(p, hits),
        "naive_log_loss": binary_log_loss(naive_p, hits),
        "calibration_slope": calibration_slope(p, hits),
    }


def _dispersion_block(
    realized: "np.typing.NDArray[np.float64]",
    pred_mean: "np.typing.NDArray[np.float64]",
    pred_var: "np.typing.NDArray[np.float64]",
) -> dict[str, float]:
    """Residual variance vs mean predicted variance: ratio > 1 means the
    model's distributions are too narrow (under-dispersed)."""
    resid = realized - pred_mean
    return {
        "residual_var": float(resid.var(ddof=1)),
        "mean_pred_var": float(pred_var.mean()),
        "ratio": float(resid.var(ddof=1) / pred_var.mean()),
    }


def summarize_props(
    totals_df: pd.DataFrame,
    corners_df: pd.DataFrame,
    cards_df: pd.DataFrame,
    skipped_cutoffs: list[str],
    settings: Settings,
) -> dict[str, Any]:
    team_p = np.concatenate(
        [
            totals_df[f"p_home_o{_tag(CANONICAL_TEAM_LINE)}"].to_numpy(dtype=np.float64),
            totals_df[f"p_away_o{_tag(CANONICAL_TEAM_LINE)}"].to_numpy(dtype=np.float64),
        ]
    )
    team_naive_p = np.concatenate(
        [
            totals_df[f"naive_p_home_o{_tag(CANONICAL_TEAM_LINE)}"].to_numpy(dtype=np.float64),
            totals_df[f"naive_p_away_o{_tag(CANONICAL_TEAM_LINE)}"].to_numpy(dtype=np.float64),
        ]
    )
    team_hits = np.concatenate(
        [
            totals_df["home_goals"].to_numpy() > CANONICAL_TEAM_LINE,
            totals_df["away_goals"].to_numpy() > CANONICAL_TEAM_LINE,
        ]
    )
    match_tag = _tag(CANONICAL_MATCH_LINE)
    totals_summary = {
        "n": len(totals_df),
        "count_log_loss": {
            "engine_total": float(-totals_df["logp_total"].mean()),
            "naive_total": float(-totals_df["naive_logp_total"].mean()),
            "engine_team": float(
                -(totals_df["logp_home"].mean() + totals_df["logp_away"].mean()) / 2
            ),
            "naive_team": float(
                -(totals_df["naive_logp_home"].mean() + totals_df["naive_logp_away"].mean()) / 2
            ),
        },
        f"team_o{_tag(CANONICAL_TEAM_LINE)}": _binary_block(team_p, team_naive_p, team_hits),
        f"match_o{match_tag}": _binary_block(
            totals_df[f"p_match_o{match_tag}"].to_numpy(dtype=np.float64),
            totals_df[f"naive_p_match_o{match_tag}"].to_numpy(dtype=np.float64),
            totals_df["total_goals"].to_numpy() > CANONICAL_MATCH_LINE,
        ),
        "dispersion_total_goals": _dispersion_block(
            totals_df["total_goals"].to_numpy(dtype=np.float64),
            totals_df["pred_mean_total"].to_numpy(dtype=np.float64),
            totals_df["pred_var_total"].to_numpy(dtype=np.float64),
        ),
    }

    def count_market(df: pd.DataFrame, canonical: float) -> dict[str, Any]:
        tag = _tag(canonical)
        return {
            "n": len(df),
            "count_log_loss": {
                "model": float(-df["logp"].mean()),
                "naive": float(-df["naive_logp"].mean()),
            },
            f"o{tag}": _binary_block(
                df[f"p_o{tag}"].to_numpy(dtype=np.float64),
                df[f"naive_p_o{tag}"].to_numpy(dtype=np.float64),
                df["realized"].to_numpy() > canonical,
            ),
            "dispersion": _dispersion_block(
                df["realized"].to_numpy(dtype=np.float64),
                df["pred_mean"].to_numpy(dtype=np.float64),
                df["pred_var"].to_numpy(dtype=np.float64),
            ),
        }

    cards_summary = count_market(cards_df, CANONICAL_CARD_LINE)
    cards_summary["ref_known"] = int(cards_df["ref_known"].sum())
    cards_summary["ref_unknown"] = int((~cards_df["ref_known"]).sum())
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "skipped_cutoffs_corners_cards": skipped_cutoffs,
        "settings": {
            "min_train_rows": settings.props.min_train_rows,
            "team_rate_pseudo_matches": settings.props.team_rate_pseudo_matches,
            "ref_rate_pseudo_matches": settings.props.ref_rate_pseudo_matches,
            "calibration_slope_range": [
                settings.props.calibration_slope_min,
                settings.props.calibration_slope_max,
            ],
        },
        "totals": totals_summary,
        "corners": count_market(corners_df, CANONICAL_CORNER_LINE),
        "cards": cards_summary,
    }


def write_props_artifacts(
    totals_df: pd.DataFrame,
    corners_df: pd.DataFrame,
    cards_df: pd.DataFrame,
    summary: dict[str, Any],
) -> list[str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    totals_df.to_parquet(TOTALS_PARQUET, index=False)
    corners_df.to_parquet(CORNERS_PARQUET, index=False)
    cards_df.to_parquet(CARDS_PARQUET, index=False)
    PROPS_SUMMARY_JSON.write_text(json.dumps(summary, indent=1, sort_keys=True))
    return [str(TOTALS_PARQUET), str(CORNERS_PARQUET), str(CARDS_PARQUET), str(PROPS_SUMMARY_JSON)]
