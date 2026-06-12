"""Walk-forward backtest of the goal engine vs Elo-only and market baselines.

Leakage rules enforced here (CLAUDE.md invariant):
- Engine: refit at each calendar-month start in the evaluation range; a match
  is predicted by the latest cutoff <= its date, fit on matches strictly
  before that cutoff. (Monthly grid = mid-tournament results inside the same
  month do NOT reach the engine — conservative by construction.)
- Elo baseline: the draw width is refit at the same cutoffs on the same
  training slice; per-match ratings are each team's rating_before from the
  Elo history (depends only on earlier matches).
- Market baseline: de-vigged average odds for that match.

Evaluation outcomes are 90-minute outcomes: a knockout match flagged
extra_time was level after 90' by construction, so its outcome is a draw
(D012; verified against football-data's separate 90' scores in tests).

Artifacts under data/processed/backtest/ — `wc26 backtest` refreshes them,
the reality-gate tests in tests/test_gates.py assert on them.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa

from wc26.backtest.baselines import devig_1x2, fit_elo_baseline
from wc26.backtest.metrics import brier, log_loss
from wc26.config import REPO_ROOT, Settings
from wc26.data.elo import compute_elo_history
from wc26.models.goal_engine import (
    GoalEngineParams,
    fit_goal_engine,
    git_sha,
    predict_grid,
    prepare_training_data,
)

BACKTEST_DIR = REPO_ROOT / "data" / "processed" / "backtest"
EVAL_PARQUET = BACKTEST_DIR / "goal_engine_backtest.parquet"
SUMMARY_JSON = BACKTEST_DIR / "goal_engine_summary.json"

EVAL_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "tournament": pa.Column(str),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "neutral": pa.Column(bool),
        "extra_time": pa.Column(bool),
        "outcome": pa.Column(int, pa.Check.isin([0, 1, 2])),
        "cutoff": pa.Column(pa.DateTime),
        "odds_home": pa.Column(float, pa.Check.gt(1.0)),
        "odds_draw": pa.Column(float, pa.Check.gt(1.0)),
        "odds_away": pa.Column(float, pa.Check.gt(1.0)),
        "elo_home": pa.Column(float),
        "elo_away": pa.Column(float),
        **{
            f"p_{model}_{o}": pa.Column(float, pa.Check.in_range(0.0, 1.0))
            for model in ("engine", "elo", "market")
            for o in ("home", "draw", "away")
        },
    },
    strict="filter",
    coerce=True,
)


def _match_results_row(
    results: pd.DataFrame, date: pd.Timestamp, home_id: str, away_id: str
) -> tuple[int, bool]:
    """Index of the results row for a team pair within ±1 day (D013).

    Returns (row index, swapped) where swapped means the source had home and
    away reversed relative to our results table. Raises on miss or ambiguity.
    """
    window = results[(results["date"] - date).abs() <= pd.Timedelta(days=1)]
    exact = window[(window["home_id"] == home_id) & (window["away_id"] == away_id)]
    if len(exact) == 1:
        return int(exact.index[0]), False
    flipped = window[(window["home_id"] == away_id) & (window["away_id"] == home_id)]
    if len(exact) == 0 and len(flipped) == 1:
        return int(flipped.index[0]), True
    raise ValueError(
        f"odds row {home_id} vs {away_id} on {date.date()}: "
        f"{len(exact)} exact / {len(flipped)} flipped results matches — "
        f"check aliases (config/teams.yaml) and date drift"
    )


def build_eval_set(
    market_odds: pd.DataFrame, results: pd.DataFrame, match_stats: pd.DataFrame
) -> pd.DataFrame:
    """Join odds to results (team pair ±1 day) and resolve 90' outcomes.

    Every odds row must match exactly one result; a miss raises rather than
    silently shrinking the evaluation sample.
    """
    results = results.reset_index(drop=True)
    et = match_stats[match_stats["extra_time"].astype(bool)]
    rows: list[dict[str, Any]] = []
    odds_cols = zip(
        market_odds["date"].tolist(),
        market_odds["tournament"].tolist(),
        market_odds["home_id"].tolist(),
        market_odds["away_id"].tolist(),
        market_odds["odds_home"].tolist(),
        market_odds["odds_draw"].tolist(),
        market_odds["odds_away"].tolist(),
        strict=True,
    )
    for raw_date, tournament, mo_home, mo_away, mo_oh, mo_od, mo_oa in odds_cols:
        date = pd.Timestamp(raw_date)
        idx, swapped = _match_results_row(results, date, str(mo_home), str(mo_away))
        res = results.iloc[idx]
        odds_home, odds_away = float(mo_oh), float(mo_oa)
        if swapped:
            odds_home, odds_away = odds_away, odds_home
        res_date = pd.Timestamp(str(res["date"]))
        home_id, away_id = str(res["home_id"]), str(res["away_id"])

        pair_et = et[
            (
                ((et["home_id"] == home_id) & (et["away_id"] == away_id))
                | ((et["home_id"] == away_id) & (et["away_id"] == home_id))
            )
            & ((et["date"] - res_date).abs() <= pd.Timedelta(days=1))
        ]
        extra_time = len(pair_et) > 0
        if extra_time:
            outcome = 1  # level after 90' by construction (D012)
        else:
            hs, as_ = int(res["home_score"]), int(res["away_score"])
            outcome = 0 if hs > as_ else 2 if hs < as_ else 1

        rows.append(
            {
                "date": res_date,
                "tournament": str(tournament),
                "home_id": home_id,
                "away_id": away_id,
                "neutral": bool(res["neutral"]),
                "extra_time": extra_time,
                "outcome": outcome,
                "odds_home": odds_home,
                "odds_draw": float(mo_od),
                "odds_away": odds_away,
            }
        )
    if len(rows) != len(market_odds):
        raise AssertionError("eval set must cover every odds row")
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _pre_match_ratings(matches: pd.DataFrame, elo_history: pd.DataFrame) -> pd.DataFrame:
    """Attach each team's rating_before its own match (exact, leak-free)."""
    before = elo_history[["date", "team_id", "rating_before"]]
    out = matches.merge(
        before.rename(columns={"team_id": "home_id", "rating_before": "elo_home"}),
        on=["date", "home_id"],
        how="left",
    ).merge(
        before.rename(columns={"team_id": "away_id", "rating_before": "elo_away"}),
        on=["date", "away_id"],
        how="left",
    )
    if out["elo_home"].isna().any() or out["elo_away"].isna().any():
        missing = out[out["elo_home"].isna() | out["elo_away"].isna()]
        raise ValueError(f"no Elo history for {len(missing)} matches, e.g.\n{missing.head(3)}")
    return out


def run_backtest(
    settings: Settings,
    results: pd.DataFrame,
    match_stats: pd.DataFrame,
    market_odds: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Walk-forward evaluation over every match with market odds."""
    eval_set = build_eval_set(market_odds, results, match_stats)
    elo_history = compute_elo_history(results, settings.elo_k)
    eval_set = _pre_match_ratings(eval_set, elo_history)

    cutoffs = sorted(eval_set["date"].dt.to_period("M").dt.start_time.unique())
    p_engine = np.zeros((len(eval_set), 3))
    p_elo = np.zeros((len(eval_set), 3))
    eval_set["cutoff"] = pd.NaT

    for cutoff in (pd.Timestamp(c) for c in cutoffs):
        in_month = (eval_set["date"] >= cutoff) & (
            eval_set["date"] < cutoff + pd.DateOffset(months=1)
        )
        if not in_month.any():
            continue
        train = prepare_training_data(
            results, match_stats, cutoff, settings.goal_engine.training_window_years
        )
        elo_asof = (
            elo_history[elo_history["date"] < cutoff].groupby("team_id")["rating_after"].last()
        )
        engine = fit_goal_engine(train, elo_asof, cutoff, settings)

        train_rated = _pre_match_ratings(train, elo_history)
        elo_baseline = fit_elo_baseline(
            train_rated["elo_home"].to_numpy(dtype=np.float64),
            train_rated["elo_away"].to_numpy(dtype=np.float64),
            train_rated["neutral"].to_numpy(dtype=np.bool_),
            _outcomes(train_rated),
        )

        idxs = eval_set.index[in_month]
        eval_set.loc[idxs, "cutoff"] = cutoff
        for i in idxs:
            row = eval_set.loc[i]
            grid = predict_grid(
                engine, str(row["home_id"]), str(row["away_id"]), bool(row["neutral"])
            )
            p_engine[i] = grid.home_draw_away
        p_elo[idxs] = elo_baseline.predict(
            eval_set.loc[idxs, "elo_home"].to_numpy(dtype=np.float64),
            eval_set.loc[idxs, "elo_away"].to_numpy(dtype=np.float64),
            eval_set.loc[idxs, "neutral"].to_numpy(dtype=np.bool_),
        )

    p_market = devig_1x2(
        eval_set[["odds_home", "odds_draw", "odds_away"]].to_numpy(dtype=np.float64)
    )

    for model, probs in (("engine", p_engine), ("elo", p_elo), ("market", p_market)):
        for j, outcome in enumerate(("home", "draw", "away")):
            eval_set[f"p_{model}_{outcome}"] = probs[:, j]

    validated = EVAL_SCHEMA.validate(eval_set)
    outcomes = validated["outcome"].to_numpy(dtype=np.int64)
    summary: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "n_matches": len(validated),
        "cutoffs": [str(pd.Timestamp(c).date()) for c in cutoffs],
        "tournaments": validated["tournament"].value_counts().to_dict(),
        "settings": {
            "decay_xi": settings.dixon_coles_decay,
            "tier_weights": settings.goal_engine.tier_weights,
            "anchor_pseudo_matches": settings.goal_engine.elo_anchor_pseudo_matches,
            "market_margin": settings.backtest.market_margin,
        },
        "metrics": {
            model: {
                "log_loss": log_loss(probs, outcomes),
                "brier": brier(probs, outcomes),
            }
            for model, probs in (("engine", p_engine), ("elo", p_elo), ("market", p_market))
        },
    }
    return validated, summary


def _outcomes(train: pd.DataFrame) -> Any:
    hs = train["home_score"].to_numpy(dtype=np.int64)
    as_ = train["away_score"].to_numpy(dtype=np.int64)
    return np.where(hs > as_, 0, np.where(hs < as_, 2, 1)).astype(np.int64)


def write_artifacts(eval_df: pd.DataFrame, summary: dict[str, Any]) -> tuple[Path, Path]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    eval_df.to_parquet(EVAL_PARQUET, index=False)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=1, sort_keys=True))
    return EVAL_PARQUET, SUMMARY_JSON


def live_market_comparison(
    params: "GoalEngineParams", fixtures: pd.DataFrame, live_odds: pd.DataFrame
) -> pd.DataFrame:
    """Model vs de-vigged live market for upcoming WC26 fixtures (gate iii).

    Live odds rows carry no date (BetExplorer fixtures page); they join to
    the fixtures table by team pair, tolerating swapped home/away. One row
    per fixture with both probability triples and the max per-outcome diff.
    """
    fx: dict[tuple[str, str], tuple[pd.Timestamp, bool]] = {
        (str(h), str(a)): (pd.Timestamp(d), bool(n))
        for h, a, d, n in zip(
            fixtures["home_id"].tolist(),
            fixtures["away_id"].tolist(),
            fixtures["date"].tolist(),
            fixtures["neutral"].tolist(),
            strict=True,
        )
    }
    rows: list[dict[str, Any]] = []
    live_cols = zip(
        live_odds["home_id"].tolist(),
        live_odds["away_id"].tolist(),
        live_odds["odds_home"].tolist(),
        live_odds["odds_draw"].tolist(),
        live_odds["odds_away"].tolist(),
        strict=True,
    )
    for lo_home, lo_away, lo_oh, lo_od, lo_oa in live_cols:
        key = (str(lo_home), str(lo_away))
        odds = [float(lo_oh), float(lo_od), float(lo_oa)]
        if key not in fx:
            key = (key[1], key[0])
            odds = [odds[2], odds[1], odds[0]]
        if key not in fx:
            raise ValueError(f"live odds {lo_home} vs {lo_away}: no fixture")
        fixture_date, fixture_neutral = fx[key]
        market = devig_1x2(np.array([odds], dtype=np.float64))[0]
        grid = predict_grid(params, key[0], key[1], neutral=fixture_neutral)
        model = np.asarray(grid.home_draw_away, dtype=np.float64)
        rows.append(
            {
                "date": fixture_date,
                "home_id": key[0],
                "away_id": key[1],
                "p_engine_home": model[0],
                "p_engine_draw": model[1],
                "p_engine_away": model[2],
                "p_market_home": market[0],
                "p_market_draw": market[1],
                "p_market_away": market[2],
                "max_abs_diff": float(np.abs(model - market).max()),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
