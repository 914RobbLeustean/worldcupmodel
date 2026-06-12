"""Market-anchor experiment (backlog #1/#2, D028): can the de-vigged market
1X2 price team totals better than the engine's own grid?

Runs on artifacts the main backtest already produces — no model is refit:

- Per props-totals eval row (191 non-ET majors), join the average market 1X2
  odds (D015, team pair ±1 day per D013, flipped orientation handled), de-vig
  (D005), solve market-implied lambdas (models/market_anchor.py), and score
  the anchored grid's team-total marginals on the SAME rows and metrics as
  the engine and naive columns already in the frame. rho=0 headline (zero
  fitted parameters → zero leak risk), rho=-0.05 sensitivity.
- Blend fit (backlog #2): the weight w minimizing pooled 1X2 log-loss of
  w*engine + (1-w)*market over the 211-match goal-engine backtest — the
  honest weight the engine's opinion deserves against a market quote.

Leakage note: the market odds are near-kickoff AVERAGES (D015), so this
experiment measures pricing off a near-close anchor; live use prices off
current quotes hours earlier — a small optimism bias, recorded in D028.

Artifacts under data/processed/backtest/; tests/test_market_anchor.py
asserts on them. `wc26 backtest` refreshes them after the main runs.
"""

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from wc26.backtest.baselines import devig_1x2
from wc26.backtest.harness import BACKTEST_DIR
from wc26.backtest.metrics import binary_log_loss, calibration_slope, log_loss
from wc26.models.goal_engine import git_sha
from wc26.models.market_anchor import market_anchored_grid
from wc26.models.team_totals import goal_marginals, p_over, total_distribution

ANCHOR_PARQUET = BACKTEST_DIR / "market_anchor_backtest.parquet"
ANCHOR_SUMMARY_JSON = BACKTEST_DIR / "market_anchor_summary.json"

RHO_HEADLINE = 0.0
RHO_SENSITIVITY = -0.05
_BLEND_GRID = np.linspace(0.0, 1.0, 101)


def _join_odds(totals_df: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """Attach (odds_home, odds_draw, odds_away) to every totals eval row.

    Team pair within ±1 day (D013); a flipped match swaps home/away odds.
    Every eval row must match exactly one odds row — both frames descend from
    the same 211-match market sample (D015), so a miss is drift, not noise.
    """
    rows: list[dict[str, float]] = []
    for r in totals_df.itertuples(index=False):
        date = pd.Timestamp(str(r.date))
        window = odds[(odds["date"] - date).abs() <= pd.Timedelta(days=1)]
        straight = window[(window["home_id"] == r.home_id) & (window["away_id"] == r.away_id)]
        flipped = window[(window["home_id"] == r.away_id) & (window["away_id"] == r.home_id)]
        if len(straight) + len(flipped) != 1:
            raise ValueError(
                f"market-anchor join: {r.home_id} v {r.away_id} on {date.date()} matched "
                f"{len(straight) + len(flipped)} odds rows — check D013 drift/aliases"
            )
        if len(straight) == 1:
            hit = straight.iloc[0]
            rows.append(
                {
                    "odds_home": float(hit["odds_home"]),
                    "odds_draw": float(hit["odds_draw"]),
                    "odds_away": float(hit["odds_away"]),
                }
            )
        else:
            hit = flipped.iloc[0]
            rows.append(
                {
                    "odds_home": float(hit["odds_away"]),
                    "odds_draw": float(hit["odds_draw"]),
                    "odds_away": float(hit["odds_home"]),
                }
            )
    return pd.concat([totals_df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _anchored_columns(joined: pd.DataFrame, rho: float) -> dict[str, NDArray[np.float64]]:
    """Anchored per-row predictions: team-total log-probs, O1.5, match O2.5."""
    n = len(joined)
    out = {
        name: np.empty(n, dtype=np.float64)
        for name in (
            "anchor_lam_home",
            "anchor_lam_away",
            "anchor_logp_home",
            "anchor_logp_away",
            "anchor_logp_total",
            "anchor_p_home_o15",
            "anchor_p_away_o15",
            "anchor_p_match_o25",
        )
    }
    fair = devig_1x2(joined[["odds_home", "odds_draw", "odds_away"]].to_numpy(dtype=np.float64))
    for i, r in enumerate(joined.itertuples(index=False)):
        grid = market_anchored_grid(float(fair[i, 0]), float(fair[i, 2]), rho=rho)
        home_dist, away_dist = goal_marginals(grid)
        total_dist = total_distribution(grid)
        hg, ag = int(str(r.home_goals)), int(str(r.away_goals))
        out["anchor_lam_home"][i] = float(grid.home_goal_expectation)
        out["anchor_lam_away"][i] = float(grid.away_goal_expectation)
        out["anchor_logp_home"][i] = float(np.log(home_dist[hg]))
        out["anchor_logp_away"][i] = float(np.log(away_dist[ag]))
        out["anchor_logp_total"][i] = float(np.log(total_dist[hg + ag]))
        out["anchor_p_home_o15"][i] = p_over(home_dist, 1.5)
        out["anchor_p_away_o15"][i] = p_over(away_dist, 1.5)
        out["anchor_p_match_o25"][i] = p_over(total_dist, 2.5)
    return out


def _team_o15_block(
    df: pd.DataFrame, p_home_col: str, p_away_col: str, label: str
) -> dict[str, float]:
    p = np.concatenate(
        [
            df[p_home_col].to_numpy(dtype=np.float64),
            df[p_away_col].to_numpy(dtype=np.float64),
        ]
    )
    hits = np.concatenate([df["home_goals"].to_numpy() > 1.5, df["away_goals"].to_numpy() > 1.5])
    return {
        f"{label}_log_loss": binary_log_loss(p, hits),
        f"{label}_calibration_slope": calibration_slope(p, hits),
    }


def _fit_blend_weight(eval_df: pd.DataFrame) -> dict[str, float]:
    """w in [0,1] minimizing pooled 1X2 log-loss of w*engine + (1-w)*market."""
    engine = eval_df[["p_engine_home", "p_engine_draw", "p_engine_away"]].to_numpy(dtype=np.float64)
    market = eval_df[["p_market_home", "p_market_draw", "p_market_away"]].to_numpy(dtype=np.float64)
    outcomes = eval_df["outcome"].to_numpy(dtype=np.int64)
    losses = [log_loss(w * engine + (1.0 - w) * market, outcomes) for w in _BLEND_GRID]
    best = int(np.argmin(losses))
    return {
        "w_star": float(_BLEND_GRID[best]),
        "log_loss_at_w_star": float(losses[best]),
        "log_loss_engine_only": float(losses[-1]),
        "log_loss_market_only": float(losses[0]),
        "n": float(len(eval_df)),
    }


def run_market_anchor_backtest(
    totals_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    odds: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score market-anchored team totals against the engine on identical rows."""
    joined = _join_odds(totals_df, odds)
    anchored = _anchored_columns(joined, RHO_HEADLINE)
    for name, col in anchored.items():
        joined[name] = col

    summary: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "n": len(joined),
        "rho_headline": RHO_HEADLINE,
        "team_count_log_loss": {
            "anchored": float(
                -(joined["anchor_logp_home"].mean() + joined["anchor_logp_away"].mean()) / 2
            ),
            "engine": float(-(joined["logp_home"].mean() + joined["logp_away"].mean()) / 2),
            "naive": float(
                -(joined["naive_logp_home"].mean() + joined["naive_logp_away"].mean()) / 2
            ),
        },
        "team_o15": (
            _team_o15_block(joined, "anchor_p_home_o15", "anchor_p_away_o15", "anchored")
            | _team_o15_block(joined, "p_home_o15", "p_away_o15", "engine")
        ),
        "match_total_exploratory": {
            "count_log_loss_anchored": float(-joined["anchor_logp_total"].mean()),
            "count_log_loss_engine": float(-joined["logp_total"].mean()),
            "count_log_loss_naive": float(-joined["naive_logp_total"].mean()),
            "o25_log_loss_anchored": binary_log_loss(
                joined["anchor_p_match_o25"].to_numpy(dtype=np.float64),
                joined["total_goals"].to_numpy() > 2.5,
            ),
            "o25_slope_anchored": calibration_slope(
                joined["anchor_p_match_o25"].to_numpy(dtype=np.float64),
                joined["total_goals"].to_numpy() > 2.5,
            ),
        },
        "blend_1x2": _fit_blend_weight(eval_df),
    }

    sens = _anchored_columns(joined, RHO_SENSITIVITY)
    summary["rho_sensitivity"] = {
        "rho": RHO_SENSITIVITY,
        "team_count_log_loss_anchored": float(
            -(sens["anchor_logp_home"].mean() + sens["anchor_logp_away"].mean()) / 2
        ),
    }
    return joined, summary


def write_market_anchor_artifacts(joined: pd.DataFrame, summary: dict[str, Any]) -> list[str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    joined.to_parquet(ANCHOR_PARQUET, index=False)
    ANCHOR_SUMMARY_JSON.write_text(json.dumps(summary, indent=1, sort_keys=True))
    return [str(ANCHOR_PARQUET), str(ANCHOR_SUMMARY_JSON)]
