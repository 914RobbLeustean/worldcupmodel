"""Phase 3 reality gates (PLAN 3.4) — hard assertions on the props backtest
artifacts. Regenerate with `uv run wc26 backtest`; tests skip only when the
artifacts have never been built (fresh clone), per repo convention.

Gates per market: (a) beat the naive baseline — historical tournament mean
(and dispersion, for counts) — on log-loss; (b) calibration slope at the
canonical line inside settings props.calibration_slope_{min,max}.

Verdicts (2026-06-12): TEAM TOTALS passes both gates and is the only Phase 3
model cleared to price. Match totals (D019) and corners/cards (D021) FAILED
and are quarantined; their tests pin the failure so a silent "improvement"
can't unflag them without a new DECISIONS entry.
"""

import json

import numpy as np
import pandas as pd
import pytest

from wc26.backtest.props import (
    CARDS_PARQUET,
    CORNERS_PARQUET,
    PROPS_SUMMARY_JSON,
    TOTALS_PARQUET,
)
from wc26.config import load_settings

SETTINGS = load_settings()

needs_props = pytest.mark.skipif(
    not (
        TOTALS_PARQUET.exists()
        and CORNERS_PARQUET.exists()
        and CARDS_PARQUET.exists()
        and PROPS_SUMMARY_JSON.exists()
    ),
    reason="props backtest artifacts missing — run `uv run wc26 backtest`",
)


@pytest.fixture(scope="module")
def summary() -> dict:  # type: ignore[type-arg]
    with PROPS_SUMMARY_JSON.open() as f:
        loaded: dict = json.load(f)  # type: ignore[type-arg]
        return loaded


def _slope_in_range(slope: float) -> None:
    assert SETTINGS.props.calibration_slope_min <= slope <= SETTINGS.props.calibration_slope_max, (
        f"calibration slope {slope:.3f} outside "
        f"[{SETTINGS.props.calibration_slope_min}, {SETTINGS.props.calibration_slope_max}]"
    )


@needs_props
def test_props_artifacts_cover_the_full_sample(summary: dict) -> None:  # type: ignore[type-arg]
    # 211 majors minus 20 ET rows (D017). Corners/cards eval starts at the
    # 2018-07 cutoff (the first with >= min_train_rows = 50 behind it: 48
    # WC18 group games + the two June-30 R16 games), so it covers the 9
    # non-ET WC18 July knockouts + WC22 (59) + Euro24 (46) + Copa24 (27).
    assert summary["totals"]["n"] == 191
    assert summary["corners"]["n"] == 141
    assert summary["cards"]["n"] == 141
    totals_df = pd.read_parquet(TOTALS_PARQUET)
    assert (totals_df["cutoff"] <= totals_df["date"]).all()
    for path in (CORNERS_PARQUET, CARDS_PARQUET):
        df = pd.read_parquet(path)
        assert (df["cutoff"] <= df["date"]).all()
        assert df["tournament"].isin(["FIFA World Cup", "UEFA Euro", "Copa América"]).all()


@needs_props
def test_gate_team_totals_beat_naive(summary: dict) -> None:  # type: ignore[type-arg]
    ll = summary["totals"]["count_log_loss"]
    assert ll["engine_team"] < ll["naive_team"], (
        f"team-totals count log-loss {ll['engine_team']:.4f} must beat naive {ll['naive_team']:.4f}"
    )
    block = summary["totals"]["team_o15"]
    assert block["log_loss"] < block["naive_log_loss"]


@needs_props
def test_gate_team_totals_calibration_slope(summary: dict) -> None:  # type: ignore[type-arg]
    _slope_in_range(summary["totals"]["team_o15"]["calibration_slope"])


@needs_props
def test_match_totals_remain_quarantined(summary: dict) -> None:  # type: ignore[type-arg]
    """D019: match totals failed their gates and are not priced. If this
    starts passing, write a DECISIONS entry before un-quarantining —
    do not let the flag silently rot."""
    block = summary["totals"]["match_o25"]
    quarantine_still_justified = (
        block["calibration_slope"] < SETTINGS.props.calibration_slope_min
        or block["log_loss"] >= block["naive_log_loss"]
    )
    assert quarantine_still_justified, (
        "match-totals gates now PASS — revisit D019 with a new DECISIONS entry "
        "before pricing match totals"
    )


@needs_props
@pytest.mark.parametrize("market,canonical", [("corners", "o95"), ("cards", "o35")])
def test_corners_and_cards_remain_quarantined(
    summary: dict,  # type: ignore[type-arg]
    market: str,
    canonical: str,
) -> None:
    """D021: corners/cards failed their PLAN 3.4 gates (lose to the naive
    moment-matched baseline AND calibration slope far out of range) and must
    not price lines. If a refit makes BOTH gates pass, this test fails on
    purpose: write a DECISIONS entry before un-quarantining."""
    block = summary[market]
    ll = block["count_log_loss"]
    slope = block[canonical]["calibration_slope"]
    slope_ok = SETTINGS.props.calibration_slope_min <= slope <= SETTINGS.props.calibration_slope_max
    gates_pass = ll["model"] < ll["naive"] and slope_ok
    assert not gates_pass, (
        f"{market} gates now PASS (count-LL {ll['model']:.4f} vs naive {ll['naive']:.4f}, "
        f"slope {slope:.2f}) — revisit D021 with a new DECISIONS entry before pricing"
    )


@needs_props
def test_cards_ref_known_accounting(summary: dict) -> None:  # type: ignore[type-arg]
    cards = summary["cards"]
    assert cards["ref_known"] + cards["ref_unknown"] == cards["n"]
    df = pd.read_parquet(CARDS_PARQUET)
    # No referee careers exist in 2018 (ESPN's officials data effectively
    # starts 2022 — the lone WC18 ref row is an ET match outside the eval),
    # so every 2018-cutoff prediction must be ref-unknown. Later cutoffs MAY
    # be known: WC22 refs accrue history from the March/June 2022 UEFA
    # playoffs and from earlier WC22 rounds — legitimate walk-forward.
    early = df[df["cutoff"] <= pd.Timestamp("2018-07-01")]
    assert len(early) > 0 and not early["ref_known"].any()


@needs_props
def test_prop_probabilities_are_well_formed() -> None:
    for path in (TOTALS_PARQUET, CORNERS_PARQUET, CARDS_PARQUET):
        df = pd.read_parquet(path)
        prob_cols = [c for c in df.columns if c.startswith(("p_", "naive_p_"))]
        probs = df[prob_cols].to_numpy(dtype=np.float64)
        assert probs.min() > 0.0 and probs.max() < 1.0
        logp_cols = [c for c in df.columns if "logp" in c]
        assert np.isfinite(df[logp_cols].to_numpy(dtype=np.float64)).all()
