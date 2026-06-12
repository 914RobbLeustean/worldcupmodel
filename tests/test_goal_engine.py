"""Goal engine on synthetic data: deterministic fit, D012 exclusion,
Elo-anchored shrinkage, and 90-minute grid invariants. No I/O, no network."""

import numpy as np
import pandas as pd
import pytest

from wc26.config import SETTINGS_PATH, load_settings
from wc26.models.goal_engine import (
    GoalEngineParams,
    fit_goal_engine,
    predict_grid,
    prepare_training_data,
)

SETTINGS = load_settings(SETTINGS_PATH)
N_TEAMS = 24
CUTOFF = pd.Timestamp("2025-12-01")


def _synthetic_results(n_rounds: int = 36, seed: int = 7) -> pd.DataFrame:
    """Round-robin-ish schedule with strength-ordered teams t00 (best) .. t23.

    Dates sit close to CUTOFF so decay weights stay near 1 and every team
    clears the Elo-anchor effective-sample threshold.
    """
    rng = np.random.default_rng(seed)
    teams = [f"t{i:02d}" for i in range(N_TEAMS)]
    strength = np.linspace(0.45, -0.45, N_TEAMS)
    rows = []
    date = pd.Timestamp("2025-04-01")
    for _ in range(n_rounds):
        order = rng.permutation(N_TEAMS)
        for k in range(0, N_TEAMS, 2):
            hi, ai = int(order[k]), int(order[k + 1])
            neutral = bool(rng.random() < 0.5)
            lam_h = np.exp(0.15 + strength[hi] - strength[ai] + (0.0 if neutral else 0.25))
            lam_a = np.exp(0.15 + strength[ai] - strength[hi])
            rows.append(
                {
                    "date": date,
                    "home_id": teams[hi],
                    "away_id": teams[ai],
                    "home_score": int(rng.poisson(lam_h)),
                    "away_score": int(rng.poisson(lam_a)),
                    "tournament": "Friendly",
                    "tier": "friendly",
                    "neutral": neutral,
                }
            )
        date += pd.Timedelta(days=6)
    return pd.DataFrame(rows)


def _elo_like(results: pd.DataFrame) -> pd.Series:
    """A plausible Elo series: ordered with team index."""
    teams = sorted(set(results["home_id"]) | set(results["away_id"]))
    return pd.Series(
        {t: 2000.0 - 25.0 * int(t[1:]) for t in teams},
        name="rating",
    )


RESULTS = _synthetic_results()
ELO = _elo_like(RESULTS)
EMPTY_STATS = pd.DataFrame(
    {"date": pd.Series(dtype="datetime64[ns]"), "home_id": [], "away_id": [], "extra_time": []}
)


@pytest.fixture(scope="module")
def fitted() -> GoalEngineParams:
    train = prepare_training_data(RESULTS, EMPTY_STATS, CUTOFF, window_years=10)
    return fit_goal_engine(train, ELO, CUTOFF, SETTINGS)


def test_prepare_excludes_extra_time_rows_with_date_drift() -> None:
    target = RESULTS.iloc[10]
    stats = pd.DataFrame(
        {
            # ESPN-style UTC date one day off, home/away swapped — both must
            # still match (D013) and knock the row out (D012).
            "date": [target["date"] + pd.Timedelta(days=1)],
            "home_id": [target["away_id"]],
            "away_id": [target["home_id"]],
            "extra_time": [True],
        }
    )
    full = prepare_training_data(RESULTS, EMPTY_STATS, CUTOFF, 10)
    pruned = prepare_training_data(RESULTS, stats, CUTOFF, 10)
    assert len(pruned) == len(full) - 1
    gone = pruned[
        (pruned["date"] == target["date"])
        & (pruned["home_id"] == target["home_id"])
        & (pruned["away_id"] == target["away_id"])
    ]
    assert gone.empty


def test_prepare_is_strictly_before_cutoff() -> None:
    cutoff = RESULTS["date"].iloc[100]
    train = prepare_training_data(RESULTS, EMPTY_STATS, cutoff, 10)
    assert (train["date"] < cutoff).all()


def test_fit_is_deterministic(fitted: GoalEngineParams) -> None:
    train = prepare_training_data(RESULTS, EMPTY_STATS, CUTOFF, 10)
    again = fit_goal_engine(train, ELO, CUTOFF, SETTINGS)
    assert again.home_advantage == pytest.approx(fitted.home_advantage)
    assert again.rho == pytest.approx(fitted.rho)
    assert again.teams["t00"].attack == pytest.approx(fitted.teams["t00"].attack)


def test_fitted_strengths_recover_ordering(fitted: GoalEngineParams) -> None:
    best, worst = fitted.teams["t00"], fitted.teams["t23"]
    assert best.attack > worst.attack
    assert best.defence < worst.defence  # lower = concedes less
    assert fitted.home_advantage > 0.05  # synthetic truth is 0.25


def test_elo_anchor_prices_unseen_team(fitted: GoalEngineParams) -> None:
    # An Elo rating between t00 (2000) and t23 (1425) was never in training:
    # the anchor regression must still produce mid-table strengths.
    elo_plus = pd.concat([ELO, pd.Series({"debutant": 1712.0})])
    train = prepare_training_data(RESULTS, EMPTY_STATS, CUTOFF, 10)
    params = fit_goal_engine(train, elo_plus, CUTOFF, SETTINGS)
    deb = params.teams["debutant"]
    assert deb.eff_matches == 0.0
    assert params.teams["t23"].attack < deb.attack < params.teams["t00"].attack


def test_shrinkage_pulls_sparse_team_toward_anchor(fitted: GoalEngineParams) -> None:
    # Refit with t01's matches cut to 2: its blended attack must sit closer
    # to the anchor line than the full fit's value does.
    keep = RESULTS[(RESULTS["home_id"] == "t01") | (RESULTS["away_id"] == "t01")].head(2)
    rest = RESULTS[(RESULTS["home_id"] != "t01") & (RESULTS["away_id"] != "t01")]
    sparse_results = pd.concat([rest, keep]).sort_values("date").reset_index(drop=True)
    train = prepare_training_data(sparse_results, EMPTY_STATS, CUTOFF, 10)
    params = fit_goal_engine(train, ELO, CUTOFF, SETTINGS)
    icept, slope = params.anchor_attack
    anchor_value = icept + slope * float(ELO["t01"])
    sparse = params.teams["t01"]
    assert sparse.eff_matches < 3.0
    # weight n/(n+10) with n<3 -> within ~25% of the pure anchor value
    assert abs(sparse.attack - anchor_value) < 0.3 * abs(
        fitted.teams["t00"].attack - fitted.teams["t23"].attack
    )


def test_grid_invariants(fitted: GoalEngineParams) -> None:
    grid = predict_grid(fitted, "t05", "t06", neutral=True)
    probs = np.asarray(grid.home_draw_away)
    assert probs.sum() == pytest.approx(1.0, abs=1e-6)
    assert probs[1] > 0.05  # 90-minute model: the draw always lives (D004)
    over = float(grid.total_goals("over", 2.5))
    assert 0.0 < over < 1.0
    assert np.asarray(grid.grid).sum() == pytest.approx(1.0, abs=1e-6)


def test_home_advantage_only_when_not_neutral(fitted: GoalEngineParams) -> None:
    home = predict_grid(fitted, "t05", "t06", neutral=False)
    neutral = predict_grid(fitted, "t05", "t06", neutral=True)
    assert home.home_draw_away[0] > neutral.home_draw_away[0]


def test_unknown_team_raises(fitted: GoalEngineParams) -> None:
    with pytest.raises(KeyError, match="atlantis"):
        predict_grid(fitted, "atlantis", "t06", neutral=True)


def test_params_roundtrip(tmp_path: object, fitted: GoalEngineParams) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "params.json"
    fitted.save(path)
    loaded = GoalEngineParams.load(path)
    assert loaded == fitted


def test_latest_model_path_orders_by_cutoff_then_fitted_at(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D023 note: same-cutoff refits tie-break on fitted_at, never the SHA.

    The filename SHAs are chosen so a pure filename sort would pick the
    WRONG file in both dimensions.
    """
    import json
    from pathlib import Path

    from wc26.models import goal_engine

    models_dir = Path(str(tmp_path))
    monkeypatch.setattr(goal_engine, "MODELS_DIR", models_dir)

    def write(sha: str, cutoff: str, fitted_at: str) -> None:
        payload = {"data_cutoff": cutoff, "fitted_at": fitted_at}
        (models_dir / f"goal_engine_{cutoff}_{sha}.json").write_text(json.dumps(payload))

    write("zzzzzzz", "2026-06-12", "2026-06-12T08:00:00+00:00")
    write("aaaaaaa", "2026-06-12", "2026-06-12T09:00:00+00:00")  # newest fit, same cutoff
    write("yyyyyyy", "2026-06-10", "2026-06-12T23:00:00+00:00")  # later fit, older cutoff
    chosen = goal_engine.latest_model_path("goal_engine")
    assert chosen.name == "goal_engine_2026-06-12_aaaaaaa.json"
