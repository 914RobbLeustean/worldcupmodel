"""WC scoring-environment offset experiment (D035, backlog #4).

Does re-levelling the engine's World Cup lambdas by exp(delta) — delta fit
walk-forward from PRIOR WC matches (goal_engine._estimate_finals_offset) —
improve WC predictions out-of-sample? Measured on the WC subset of the props
eval (WC18 + WC22), each match predicted with a model fit strictly before its
cutoff, the offset estimated from WC matches before THAT cutoff:

- WC18 matches: offset from WC14/WC10 (in the training window).
- WC22 matches: offset from WC18.
- WC26 live: offset from WC18 + WC22.

So the WC eval here is scored with offsets that knew only earlier WCs — clean
walk-forward. Diagnosis (2026-06-13): the engine runs 21% light on WC totals
(2.20 vs 2.66), roughly symmetric across favorite (x1.22) and underdog
(x1.18), while Euro24/Copa24 are within ~4% — hence a WC-only multiplicative
offset, not a finals-wide one.

Pre-registered SHIP criterion (D035), all on the WC subset:
1. team-total count log-loss improves (offset < base), AND
2. the WC O1.5 calibration slope stays in props.calibration_slope_{min,max}, AND
3. the full 1X2 gates still pass when the offset is applied to WC matches
   (checked by tests/test_gates.py after `wc26 backtest`).
Match totals stay QUARANTINED regardless unless the WC O2.5 slope enters the
gate band (it is not expected to — D019/D030).

Artifact under data/processed/backtest/; tests/test_wc_offset.py pins the
verdict. Runs inside `wc26 backtest`.
"""

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from wc26.backtest.harness import BACKTEST_DIR
from wc26.backtest.metrics import binary_log_loss, calibration_slope
from wc26.backtest.props import _monthly_cutoffs
from wc26.config import Settings
from wc26.data.elo import compute_elo_history
from wc26.models.goal_engine import fit_goal_engine, git_sha, predict_grid, prepare_training_data
from wc26.models.prop_features import props_universe
from wc26.models.team_totals import (
    distribution_mean_var,
    goal_marginals,
    p_over,
    total_distribution,
)

WC_OFFSET_SUMMARY_JSON = BACKTEST_DIR / "wc_offset_summary.json"


def run_wc_offset_experiment(
    settings: Settings, results: pd.DataFrame, match_stats: pd.DataFrame
) -> dict[str, Any]:
    """Score WC totals with vs without the finals offset, walk-forward."""
    universe = props_universe(
        match_stats[match_stats["date"] < pd.Timestamp("2026-01-01")], results
    )
    wc = universe[(~universe["qualifier"]) & (universe["tournament"] == "FIFA World Cup")]
    elo_history = compute_elo_history(results, settings.elo_k)

    rows: list[dict[str, Any]] = []
    offsets: dict[str, float] = {}
    for cutoff in _monthly_cutoffs(wc["date"]):
        in_month = wc[(wc["date"] >= cutoff) & (wc["date"] < cutoff + pd.DateOffset(months=1))]
        if in_month.empty:
            continue
        train = prepare_training_data(
            results, match_stats, cutoff, settings.goal_engine.training_window_years
        )
        elo_asof = (
            elo_history[elo_history["date"] < cutoff].groupby("team_id")["rating_after"].last()
        )
        engine = fit_goal_engine(train, elo_asof, cutoff, settings)
        offsets[str(cutoff.date())] = engine.finals_scoring_offset
        for r in in_month.itertuples(index=False):
            home, away, neutral = str(r.home_id), str(r.away_id), bool(r.neutral)
            hg, ag = int(str(r.home_score)), int(str(r.away_score))
            outcome = 0 if hg > ag else (1 if hg == ag else 2)
            for tag, use in (("base", False), ("offset", True)):
                grid = predict_grid(engine, home, away, neutral, apply_finals_offset=use)
                home_dist, away_dist = goal_marginals(grid)
                total_dist = total_distribution(grid)
                p_1x2 = np.asarray(grid.home_draw_away, dtype=np.float64)
                rows.append(
                    {
                        "tag": tag,
                        "home_goals": hg,
                        "away_goals": ag,
                        "total_goals": hg + ag,
                        "logp_home": float(np.log(home_dist[hg])),
                        "logp_away": float(np.log(away_dist[ag])),
                        "logp_total": float(np.log(total_dist[hg + ag])),
                        "logp_1x2": float(np.log(p_1x2[outcome] / p_1x2.sum())),
                        "p_home_o15": p_over(home_dist, 1.5),
                        "p_away_o15": p_over(away_dist, 1.5),
                        "p_match_o25": p_over(total_dist, 2.5),
                        "pred_total": distribution_mean_var(total_dist)[0],
                    }
                )
    df = pd.DataFrame(rows)

    def block(tag: str) -> dict[str, float]:
        d = df[df["tag"] == tag]
        team_p = np.concatenate(
            [d["p_home_o15"].to_numpy(np.float64), d["p_away_o15"].to_numpy(np.float64)]
        )
        team_hits = np.concatenate(
            [d["home_goals"].to_numpy() > 1.5, d["away_goals"].to_numpy() > 1.5]
        )
        match_hits = d["total_goals"].to_numpy() > 2.5
        return {
            "x1x2_log_loss": float(-d["logp_1x2"].mean()),
            "team_count_log_loss": float(-(d["logp_home"].mean() + d["logp_away"].mean()) / 2),
            "team_o15_log_loss": binary_log_loss(team_p, team_hits),
            "team_o15_slope": calibration_slope(team_p, team_hits),
            "match_count_log_loss": float(-d["logp_total"].mean()),
            "match_o25_log_loss": binary_log_loss(
                d["p_match_o25"].to_numpy(np.float64), match_hits
            ),
            "match_o25_slope": calibration_slope(d["p_match_o25"].to_numpy(np.float64), match_hits),
            "pred_total_mean": float(d["pred_total"].mean()),
            "realized_total_mean": float(d["total_goals"].mean()),
        }

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "n_wc_matches": int(len(df) // 2),
        "offsets_by_cutoff": offsets,
        "base": block("base"),
        "offset": block("offset"),
    }


def write_wc_offset_artifact(summary: dict[str, Any]) -> str:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    WC_OFFSET_SUMMARY_JSON.write_text(json.dumps(summary, indent=1, sort_keys=True))
    return str(WC_OFFSET_SUMMARY_JSON)
