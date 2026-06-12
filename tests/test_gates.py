"""Phase 2 reality gates — hard assertions, not judgment calls (PLAN 2.3).

They assert on the walk-forward artifacts under data/processed/backtest/ and
the latest fitted model. Regenerate with `wc26 backtest` / `wc26 refit`;
tests skip only when the artifacts have never been built (fresh clone), in
line with the repo's full-data test convention.

Gate ii is deliberately upside-down vs normal instincts: BEATING the market
in a backtest is treated as evidence of leakage until investigated (the
market baseline saw the matches; we must not have).
"""

import json

import numpy as np
import pandas as pd
import pytest

from wc26.backtest.harness import EVAL_PARQUET, SUMMARY_JSON
from wc26.config import load_settings

SETTINGS = load_settings()

needs_backtest = pytest.mark.skipif(
    not (EVAL_PARQUET.exists() and SUMMARY_JSON.exists()),
    reason="backtest artifacts missing — run `uv run wc26 backtest`",
)


@pytest.fixture(scope="module")
def summary() -> dict:  # type: ignore[type-arg]
    with SUMMARY_JSON.open() as f:
        loaded: dict = json.load(f)  # type: ignore[type-arg]
        return loaded


@needs_backtest
def test_gate_artifacts_cover_the_full_sample(summary: dict) -> None:  # type: ignore[type-arg]
    assert summary["n_matches"] == 211
    assert summary["tournaments"] == {
        "FIFA World Cup": 128,
        "UEFA Euro": 51,
        "Copa América": 32,
    }
    eval_df = pd.read_parquet(EVAL_PARQUET)
    assert len(eval_df) == summary["n_matches"]
    assert int(eval_df["extra_time"].sum()) == 20  # 5 per tournament, known
    # Every prediction came from a cutoff at or before the match date.
    assert (eval_df["cutoff"] <= eval_df["date"]).all()


@needs_backtest
def test_gate_i_engine_beats_elo_baseline(summary: dict) -> None:  # type: ignore[type-arg]
    engine = summary["metrics"]["engine"]
    elo = summary["metrics"]["elo"]
    assert engine["log_loss"] < elo["log_loss"], (
        f"engine {engine['log_loss']:.4f} must beat Elo-only {elo['log_loss']:.4f}"
    )
    assert engine["brier"] < elo["brier"]


@needs_backtest
def test_gate_ii_engine_does_not_beat_the_market(summary: dict) -> None:  # type: ignore[type-arg]
    engine = summary["metrics"]["engine"]
    market = summary["metrics"]["market"]
    margin = SETTINGS.backtest.market_margin
    assert engine["log_loss"] > market["log_loss"] - margin, (
        f"engine log-loss {engine['log_loss']:.4f} beats the de-vigged market "
        f"{market['log_loss']:.4f} by more than {margin} — treat as a LEAK and "
        f"investigate before celebrating (CLAUDE.md risk register)"
    )


@needs_backtest
def test_gate_engine_probabilities_are_well_formed() -> None:
    eval_df = pd.read_parquet(EVAL_PARQUET)
    for model in ("engine", "elo", "market"):
        probs = eval_df[[f"p_{model}_home", f"p_{model}_draw", f"p_{model}_away"]].to_numpy()
        assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-6)
        assert probs.min() > 0.0


def test_gate_iii_live_1x2_sane_vs_market() -> None:
    """Engine vs de-vigged live market across upcoming WC26 fixtures.

    Thresholds (settings.yaml `backtest:`) catch insanity — team mix-ups,
    inverted strong favorites, broken home advantage — while allowing honest
    model-vs-market disagreement; rationale in docs/MODEL.md.
    """
    from wc26.backtest.harness import live_market_comparison
    from wc26.data.market_odds import fetch_wc26_live_odds, latest_wc26_snapshot_date
    from wc26.data.results import PROCESSED_DIR
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path

    day = latest_wc26_snapshot_date()
    if day is None:
        pytest.skip("no cached live odds snapshot — any predict/backtest day creates one")
    try:
        params_path = latest_params_path()
    except FileNotFoundError:
        pytest.skip("no fitted model — run `uv run wc26 refit`")
    params = GoalEngineParams.load(params_path)
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    live = fetch_wc26_live_odds(day)  # cache hit, no network

    comp = live_market_comparison(params, fixtures, live)
    assert len(comp) >= 10

    bt = SETTINGS.backtest
    worst = comp.loc[comp["max_abs_diff"].idxmax()]
    assert comp["max_abs_diff"].max() <= bt.sanity_max_abs_diff, (
        f"{worst['home_id']} v {worst['away_id']}: per-outcome diff "
        f"{worst['max_abs_diff']:.3f} > {bt.sanity_max_abs_diff}"
    )
    assert comp["max_abs_diff"].mean() <= bt.sanity_mean_abs_diff

    market = comp[["p_market_home", "p_market_draw", "p_market_away"]].to_numpy()
    model = comp[["p_engine_home", "p_engine_draw", "p_engine_away"]].to_numpy()
    strong = market.max(axis=1) >= bt.sanity_favorite_prob
    assert (market[strong].argmax(axis=1) == model[strong].argmax(axis=1)).all(), (
        "model inverts a strong market favorite — check team resolution and home advantage"
    )
