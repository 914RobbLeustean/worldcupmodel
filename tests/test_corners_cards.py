"""Corners/cards models on synthetic universes: determinism, leak guards,
ref-unknown widening, persistence round-trips."""

import numpy as np
import pandas as pd
import pytest

from wc26.config import load_settings
from wc26.models.cards import CardsParams, fit_cards, predict_cards
from wc26.models.corners import CornersParams, fit_corners, predict_corners
from wc26.models.goal_engine import GoalEngineParams, TeamStrength

SETTINGS = load_settings()
CUTOFF = pd.Timestamp("2031-01-01")
TEAMS = [f"t{i}" for i in range(10)]

ENGINE = GoalEngineParams(
    fitted_at="2031-01-01T00:00:00+00:00",
    git_sha="testsha0000000",
    data_cutoff="2031-01-01",
    n_matches=100,
    decay_xi=0.00126,
    tier_weights={"world_cup": 3.0},
    anchor_pseudo_matches=10.0,
    home_advantage=0.25,
    rho=-0.05,
    anchor_attack=(0.0, 0.0),
    anchor_defence=(0.0, 0.0),
    teams={
        t: TeamStrength(attack=0.1 * (i % 4), defence=-0.05 * i, eff_matches=20.0)
        for i, t in enumerate(TEAMS)
    },
)

STAT_COLS = [
    f"{stat}_{side}"
    for stat in ("corners", "yellows", "reds", "fouls", "shots")
    for side in ("home", "away")
]


def _universe(n: int = 80, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    refs = [f"Ref {c}" for c in "ABCDE"]
    for i in range(n):
        home, away = rng.choice(TEAMS, size=2, replace=False)
        ref = refs[i % len(refs)] if i % 3 != 0 else None
        # Ref A..E have escalating card tendencies so ref_rate is identifiable.
        ref_level = (refs.index(ref) if ref else 2) * 0.6
        rows.append(
            {
                "date": pd.Timestamp("2030-01-01") + pd.Timedelta(days=3 * i),
                "tournament": "FIFA World Cup",
                "home_id": home,
                "away_id": away,
                "home_score": int(rng.poisson(1.3)),
                "away_score": int(rng.poisson(1.1)),
                "referee": ref,
                "corners_home": float(rng.poisson(5)),
                "corners_away": float(rng.poisson(4)),
                "yellows_home": float(rng.poisson(1.0 + ref_level / 2)),
                "yellows_away": float(rng.poisson(1.0 + ref_level / 2)),
                "reds_home": float(rng.binomial(1, 0.05)),
                "reds_away": float(rng.binomial(1, 0.05)),
                "fouls_home": float(rng.poisson(12)),
                "fouls_away": float(rng.poisson(11)),
                "shots_home": float(rng.poisson(13)),
                "shots_away": float(rng.poisson(11)),
                "matchday": int(rng.integers(1, 4)),
                "knockout": bool(rng.random() < 0.2),
                "neutral": True,
                "qualifier": bool(i < 20),
            }
        )
    df = pd.DataFrame(rows)
    df["total_corners"] = (df["corners_home"] + df["corners_away"]).astype(int)
    df["total_cards"] = (
        df["yellows_home"] + df["yellows_away"] + df["reds_home"] + df["reds_away"]
    ).astype(int)
    return df


UNIVERSE = _universe()
RIVALRIES = frozenset({frozenset(("t0", "t1"))})


def test_fit_corners_deterministic_and_predict_well_formed() -> None:
    first = fit_corners(UNIVERSE, ENGINE, CUTOFF, SETTINGS)
    second = fit_corners(UNIVERSE, ENGINE, CUTOFF, SETTINGS)
    assert first.coef == second.coef
    assert first.alpha == second.alpha
    assert "qualifier" in first.feature_names
    dist = predict_corners(first, ENGINE, "t0", "t1", True, matchday=2, knockout=False)
    assert dist.sum() == pytest.approx(1.0)
    assert dist.min() >= 0
    mu = float(np.sum(np.arange(len(dist)) * dist))
    assert 5 < mu < 15


def test_fit_corners_leak_guard() -> None:
    with pytest.raises(ValueError, match="leak"):
        fit_corners(UNIVERSE, ENGINE, pd.Timestamp("2030-06-01"), SETTINGS)


def test_fit_corners_minimum_sample() -> None:
    with pytest.raises(ValueError, match="worldq"):
        fit_corners(UNIVERSE.head(20), ENGINE, CUTOFF, SETTINGS)


def test_corners_unseen_team_falls_back_to_mean_rates() -> None:
    params = fit_corners(UNIVERSE, ENGINE, CUTOFF, SETTINGS)
    engine = GoalEngineParams(
        **{
            **ENGINE.__dict__,
            "teams": {**ENGINE.teams, "zz": TeamStrength(0.0, 0.0, 0.0)},
        }
    )
    dist = predict_corners(params, engine, "zz", "t1", True, matchday=1, knockout=False)
    assert dist.sum() == pytest.approx(1.0)


def test_corners_params_roundtrip(tmp_path) -> None:
    params = fit_corners(UNIVERSE, ENGINE, CUTOFF, SETTINGS)
    path = tmp_path / "corners_test.json"
    params.save(path)
    assert CornersParams.load(path) == params


def test_fit_cards_uses_ref_rate_and_predicts() -> None:
    params = fit_cards(UNIVERSE, RIVALRIES, CUTOFF, SETTINGS)
    assert "ref_rate" in params.feature_names
    assert params.coef["ref_rate"] != 0.0
    pred = predict_cards(params, "t0", "t2", "Ref D", knockout=False, rivalry=False)
    assert pred.ref_known
    assert pred.distribution.sum() == pytest.approx(1.0)


def test_cards_ref_unknown_widens_and_flags() -> None:
    params = fit_cards(UNIVERSE, RIVALRIES, CUTOFF, SETTINGS)
    known = predict_cards(params, "t0", "t2", "Ref D", knockout=False, rivalry=False)
    unknown = predict_cards(params, "t0", "t2", None, knockout=False, rivalry=False)
    never_seen = predict_cards(
        params, "t0", "t2", "Mystery Official", knockout=False, rivalry=False
    )
    assert not unknown.ref_known and not never_seen.ref_known
    assert unknown.alpha_used > known.alpha_used
    assert unknown.alpha_used == never_seen.alpha_used
    # widened alpha -> strictly fatter distribution for the same mean regime
    assert unknown.alpha_used > params.alpha


def test_cards_leak_guard_and_roundtrip(tmp_path) -> None:
    with pytest.raises(ValueError, match="leak"):
        fit_cards(UNIVERSE, RIVALRIES, pd.Timestamp("2030-02-01"), SETTINGS)
    params = fit_cards(UNIVERSE, RIVALRIES, CUTOFF, SETTINGS)
    path = tmp_path / "cards_test.json"
    params.save(path)
    assert CardsParams.load(path) == params


def test_cards_rivalry_dropped_without_support() -> None:
    # UNIVERSE has no t0-t1 fixture guaranteed >= min_flag_support, so the
    # rivalry feature must be dropped rather than fit on noise.
    params = fit_cards(UNIVERSE, RIVALRIES, CUTOFF, SETTINGS)
    rivalry_rows = sum(
        1
        for h, a in zip(UNIVERSE["home_id"], UNIVERSE["away_id"], strict=True)
        if frozenset((h, a)) in RIVALRIES
    )
    if rivalry_rows < SETTINGS.props.min_flag_support:
        assert "rivalry" not in params.feature_names
    else:
        assert "rivalry" in params.feature_names
