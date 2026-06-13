"""Historical prop-line evaluation (backlog #3 + #8, D036).

Scores the consensus CLOSING match-total Over/Under lines the user collected
(Euro 2024 + WC 2022, data/manual/historical_prop_lines.csv) against realized
90-minute results. Three questions, none of which the project could answer
before — the live model had only ever beaten a no-skill Poisson naive, never
a market price:

  1. CLOSE CALIBRATION — is the consensus match-total close sharp? Binary
     log-loss + calibration slope of the de-vigged O/U close vs outcomes, per
     line, against a base-rate naive. (The founding premise — that soft-book
     lines are beatable — is tested here against the CONSENSUS close; Superbet's
     own softness is measured forward by live CLV, D033/D034.)

  2. ANCHORING CONSISTENCY (D028, validated against a real total price for the
     first time) — solve the DC grid to the de-vigged market 1X2 (D015
     market_odds, rho=0, the leak-free headline) and read off P(match over):
     does it reproduce the independent total close? Which scores better on
     outcomes?

  3. EDGE THRESHOLD (#8) — the live mechanism (D032) is edge = anchored_p -
     prop_fair_p. Here that is anchored P(over) - close P(over) on a real
     historical sample; report its distribution and whether betting the
     indicated side when |edge| > t actually beats the close. This is the
     measured book-error scale the Phase-0 0.05 guess never had.

EXTRA TIME (D012/D017): the user's O/U odds are 90'; results.parquet stores
ET-INCLUSIVE knockout scores with no flag in that table. Every extra_time
match (from match_stats) is a 90' DRAW for 1X2, and its 90' TOTAL is taken
from NINETY_MIN_TOTAL below — verified against the match record. A two-way
assertion ties that patch to the match_stats flag so a future ET match cannot
be scored on its ET score by accident.

Self-contained: no refit, no engine artifacts (rho=0). `wc26 eval-prop-lines`
writes the artifacts; tests/test_prop_lines.py pins the verdict.
"""

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from penaltyblog.implied import calculate_implied

from wc26.backtest.baselines import devig_1x2
from wc26.backtest.harness import BACKTEST_DIR
from wc26.backtest.metrics import binary_log_loss, calibration_slope
from wc26.models.goal_engine import git_sha
from wc26.models.market_anchor import market_anchored_grid
from wc26.models.team_totals import p_over, total_distribution

PROP_LINES_PARQUET = BACKTEST_DIR / "prop_lines_backtest.parquet"
PROP_LINES_SUMMARY_JSON = BACKTEST_DIR / "prop_lines_summary.json"

RHO_HEADLINE = 0.0  # leak-free: zero fitted parameters (matches D028)
HEADLINE_LINE = 2.5
_DAY = pd.Timedelta(days=1)

# 90-minute TOTAL goals for the 10 extra-time matches (D012/D017). results
# stores the ET-inclusive score; 4 of these differ from it (croatia/brazil,
# argentina/france, england/slovakia, spain/germany scored in ET), 6 did not.
NINETY_MIN_TOTAL: dict[tuple[str, frozenset[str]], int] = {
    ("FIFA World Cup", frozenset({"croatia", "japan"})): 2,
    ("FIFA World Cup", frozenset({"morocco", "spain"})): 0,
    ("FIFA World Cup", frozenset({"croatia", "brazil"})): 0,
    ("FIFA World Cup", frozenset({"netherlands", "argentina"})): 4,
    ("FIFA World Cup", frozenset({"argentina", "france"})): 4,
    ("UEFA Euro", frozenset({"england", "slovakia"})): 2,
    ("UEFA Euro", frozenset({"portugal", "slovenia"})): 0,
    ("UEFA Euro", frozenset({"spain", "germany"})): 2,
    ("UEFA Euro", frozenset({"portugal", "france"})): 0,
    ("UEFA Euro", frozenset({"england", "switzerland"})): 2,
}


def _devig_over(over: float, under: float) -> float:
    """De-vigged P(over) of a two-way O/U close (multiplicative, D005)."""
    return float(calculate_implied([over, under], method="multiplicative").probabilities[0])


def _et_pairs(stats: pd.DataFrame) -> set[tuple[str, frozenset[str]]]:
    s = stats.copy()
    s["year"] = pd.to_datetime(s["date"]).dt.year
    s = s[
        (
            ((s.tournament == "UEFA Euro") & (s.year == 2024))
            | ((s.tournament == "FIFA World Cup") & (s.year == 2022))
        )
        & (s.extra_time)
    ]
    return {
        (str(r.tournament), frozenset((str(r.home_id), str(r.away_id))))
        for r in s.itertuples(index=False)
    }


def attach_realized(
    prop_df: pd.DataFrame, results: pd.DataFrame, stats: pd.DataFrame
) -> pd.DataFrame:
    """Per-match realized 90' total + 1X2 outcome, joined to every line row.

    Result row matched by canonical pair within ±1 day of the line's date
    (D013). ET matches: 1X2 outcome = draw, 90' total from NINETY_MIN_TOTAL.
    """
    et = _et_pairs(stats)
    # the patch must describe exactly the extra-time matches — no more, no less
    if set(NINETY_MIN_TOTAL) != et:
        raise ValueError(
            f"NINETY_MIN_TOTAL keys do not match match_stats extra_time set; "
            f"missing={et - set(NINETY_MIN_TOTAL)} extra={set(NINETY_MIN_TOTAL) - et}"
        )

    res = results.copy()
    res["date"] = pd.to_datetime(res["date"])
    res["year"] = res["date"].dt.year
    res = res[
        ((res.tournament == "UEFA Euro") & (res.year == 2024))
        | ((res.tournament == "FIFA World Cup") & (res.year == 2022))
    ]
    # (tournament, pair) -> result rows; the date window then disambiguates a
    # rematch (WC22 Croatia v Morocco), with no per-row apply (B023-safe).
    res_by_key: dict[tuple[str, frozenset[str]], list[Any]] = {}
    for r in res.itertuples(index=False):
        pair = frozenset((str(r.home_id), str(r.away_id)))
        res_by_key.setdefault((str(r.tournament), pair), []).append(r)

    matches = prop_df[["tournament", "date", "home_team", "away_team"]].drop_duplicates()
    realized: list[dict[str, Any]] = []
    for m in matches.itertuples(index=False):
        date = pd.Timestamp(str(m.date))
        key = (str(m.tournament), frozenset((str(m.home_team), str(m.away_team))))
        cands = [c for c in res_by_key.get(key, []) if abs(pd.Timestamp(c.date) - date) <= _DAY]
        if len(cands) != 1:
            raise ValueError(
                f"realized join: {key} on {date.date()} "
                f"matched {len(cands)} results rows (D013 window)"
            )
        hit = cands[0]
        hs, as_ = int(hit.home_score), int(hit.away_score)
        is_et = key in et
        total_90 = NINETY_MIN_TOTAL[key] if is_et else hs + as_
        # ET => 90' draw (that is why it went to ET); else the sign of the score
        outcome = 1 if (is_et or hs == as_) else (0 if hs > as_ else 2)
        realized.append(
            {
                "tournament": m.tournament,
                "date": m.date,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "total_goals_90": total_90,
                "outcome_1x2": outcome,
                "extra_time": is_et,
            }
        )
    return prop_df.merge(
        pd.DataFrame(realized), on=["tournament", "date", "home_team", "away_team"], how="left"
    )


def _attach_anchor(df: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """Attach the de-vigged market 1X2 and the anchored grid's P(match over).

    market_odds joined on the exact (home_id, away_id, date) the line carries
    (both descend from market_odds, so the key is exact even for a rematch).
    """
    o = odds.copy()
    o["_date"] = pd.to_datetime(o["date"]).dt.date.astype(str)
    o = o[["home_id", "away_id", "_date", "odds_home", "odds_draw", "odds_away"]]
    left = df.copy()
    left["_date"] = pd.to_datetime(left["date"]).dt.date.astype(str)
    merged = left.merge(
        o,
        left_on=["home_team", "away_team", "_date"],
        right_on=["home_id", "away_id", "_date"],
        how="left",
    ).drop(columns=["_date", "home_id", "away_id"])
    if merged["odds_home"].isna().any():
        miss = merged[merged["odds_home"].isna()][
            ["home_team", "away_team", "date"]
        ].drop_duplicates()
        raise ValueError(f"market_odds 1X2 missing for {len(miss)} matches:\n{miss}")

    fair = devig_1x2(merged[["odds_home", "odds_draw", "odds_away"]].to_numpy(dtype=np.float64))
    anchored_over = np.empty(len(merged), dtype=np.float64)
    grid_cache: dict[tuple[float, float], NDArray[np.float64]] = {}
    for i, (ph, pa, line) in enumerate(
        zip(fair[:, 0], fair[:, 2], merged["line"].to_numpy(dtype=np.float64), strict=True)
    ):
        key = (round(float(ph), 6), round(float(pa), 6))
        dist = grid_cache.get(key)
        if dist is None:
            dist = total_distribution(market_anchored_grid(float(ph), float(pa), rho=RHO_HEADLINE))
            grid_cache[key] = dist
        anchored_over[i] = p_over(dist, float(line))
    merged["fair_p_home"] = fair[:, 0]
    merged["anchored_p_over"] = anchored_over
    return merged


def _calibration_block(p: NDArray[np.float64], hits: NDArray[np.bool_]) -> dict[str, Any]:
    base = float(hits.mean())
    close_ll = binary_log_loss(p, hits)
    naive_ll = binary_log_loss(np.full_like(p, base), hits)
    y = hits.astype(np.float64)
    # point-biserial corr = robust discrimination (sharpness) of the close;
    # ~0 means the line does not separate over from under outcomes at all
    corr = float(np.corrcoef(p, y)[0, 1]) if p.std() > 0 else 0.0
    out: dict[str, Any] = {
        "n": len(hits),
        "base_rate_over": base,
        "close_log_loss": close_ll,
        "naive_log_loss": naive_ll,
        "log_loss_skill_vs_naive": naive_ll - close_ll,  # > 0: close beats base rate
        "corr_with_outcome": corr,
        "mean_abs_book_error": float(np.mean(np.abs(p - y))),
    }
    # the calibration slope needs both classes and enough spread to fit
    try:
        out["calibration_slope"] = (
            calibration_slope(p, hits) if 0 < hits.sum() < len(hits) else None
        )
    except Exception:  # perfect separation on a tail line — not informative
        out["calibration_slope"] = None
    return out


def run_prop_lines_eval(
    prop_df: pd.DataFrame, results: pd.DataFrame, stats: pd.DataFrame, odds: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = attach_realized(prop_df, results, stats)
    df = _attach_anchor(df, odds)
    df["close_p_over"] = [
        _devig_over(o, u) for o, u in zip(df["over_odds"], df["under_odds"], strict=True)
    ]
    df["over_hit"] = df["total_goals_90"] > df["line"]
    df["edge_anchor_vs_close"] = df["anchored_p_over"] - df["close_p_over"]

    n_matches = len(df[["tournament", "date", "home_team", "away_team"]].drop_duplicates())
    summary: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "source": "oddsportal_avg consensus close (D036)",
        "n_matches": n_matches,
        "n_lines": len(df),
        "rho_headline": RHO_HEADLINE,
        "close_calibration": {},
        "anchoring": {},
        "edge_threshold": {},
    }

    # Block 1 — close calibration per line
    for line in sorted(df["line"].unique()):
        sub = df[df["line"] == line]
        summary["close_calibration"][f"{line:.1f}"] = _calibration_block(
            sub["close_p_over"].to_numpy(dtype=np.float64),
            sub["over_hit"].to_numpy(dtype=bool),
        )

    # Block 2 — anchoring consistency (headline line + ladder-wide)
    head = df[df["line"] == HEADLINE_LINE]
    diff = (head["anchored_p_over"] - head["close_p_over"]).to_numpy(dtype=np.float64)
    summary["anchoring"] = {
        "headline_line": HEADLINE_LINE,
        "n": len(head),
        "mean_abs_diff_p_over": float(np.mean(np.abs(diff))),
        "corr_p_over": float(np.corrcoef(head["anchored_p_over"], head["close_p_over"])[0, 1]),
        "anchored_log_loss": binary_log_loss(
            head["anchored_p_over"].to_numpy(dtype=np.float64), head["over_hit"].to_numpy(bool)
        ),
        "close_log_loss": binary_log_loss(
            head["close_p_over"].to_numpy(dtype=np.float64), head["over_hit"].to_numpy(bool)
        ),
        "mean_abs_diff_p_over_ladder": float(np.mean(np.abs(df["edge_anchor_vs_close"]))),
    }

    # Block 3 — edge threshold (#8): does the live anchor-vs-close edge pay?
    edge = head["edge_anchor_vs_close"].to_numpy(dtype=np.float64)
    over_hit = head["over_hit"].to_numpy(bool)
    close_p = head["close_p_over"].to_numpy(dtype=np.float64)
    curve = []
    for t in (0.02, 0.03, 0.05, 0.07, 0.10):
        side = np.where(edge > t, 1, np.where(edge < -t, -1, 0))
        bet = side != 0
        n = int(bet.sum())
        if n == 0:
            curve.append({"t": t, "n_bets": 0, "hit_rate": None, "vs_close_realized_edge": None})
            continue
        bet_hit = np.where(side == 1, over_hit, ~over_hit)[bet]
        # realized edge vs the close: outcome prob the bet side actually had,
        # minus what the close gave that side
        close_side = np.where(side == 1, close_p, 1.0 - close_p)[bet]
        outcome_side = bet_hit.astype(np.float64)
        curve.append(
            {
                "t": float(t),
                "n_bets": n,
                "hit_rate": float(bet_hit.mean()),
                "vs_close_realized_edge": float(np.mean(outcome_side - close_side)),
            }
        )
    summary["edge_threshold"] = {
        "headline_line": HEADLINE_LINE,
        "mean_abs_book_error": summary["close_calibration"][f"{HEADLINE_LINE:.1f}"][
            "mean_abs_book_error"
        ],
        "abs_edge_quantiles": {
            f"{q}": float(np.quantile(np.abs(edge), q)) for q in (0.5, 0.75, 0.9)
        },
        "curve": curve,
    }
    return df, summary


def write_prop_lines_artifacts(df: pd.DataFrame, summary: dict[str, Any]) -> list[str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROP_LINES_PARQUET, index=False)
    PROP_LINES_SUMMARY_JSON.write_text(json.dumps(summary, indent=1, sort_keys=True))
    return [str(PROP_LINES_PARQUET), str(PROP_LINES_SUMMARY_JSON)]
