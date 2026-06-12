"""Simulator gates as tests (PLAN 5.4 / Phase 5.5).

- decided outcomes collapse to certainty,
- P(champion) sums to exactly 1,
- deterministic under the fixed seed,
- an eliminated team is at 0% everywhere once the result lands,
all on a constructed tournament (synthetic engine params + synthetic
fixtures through the real build_group_stage boundary), so the gates hold on
a fresh clone with no processed data.
"""

import numpy as np
import pandas as pd
import pytest

from wc26.data.teams import registry
from wc26.models.goal_engine import GoalEngineParams, TeamStrength
from wc26.sim.bracket import load_allocation, load_bracket
from wc26.sim.mc import _ko_orientation, rankings_frame, run_simulation
from wc26.sim.tracker import build_group_stage, tournament_state

BRACKET = load_bracket()
ALLOCATION = load_allocation(BRACKET)
REG = registry()
GROUPS = {letter: tuple(t.id for t in REG.group(letter)) for letter in "ABCDEFGHIJKL"}
NO_ELO: dict[str, float] = {}
EMPTY_STATS = pd.DataFrame()


def synthetic_params() -> GoalEngineParams:
    teams = {
        t: TeamStrength(attack=0.3 - 0.012 * i, defence=-0.3 + 0.012 * i, eff_matches=20.0)
        for i, t in enumerate(sorted(REG.wc26_ids))
    }
    return GoalEngineParams(
        fitted_at="2026-06-12T00:00:00+00:00",
        git_sha="testsha",
        data_cutoff="2026-06-12",
        n_matches=100,
        decay_xi=0.001,
        tier_weights={"world_cup": 3.0},
        anchor_pseudo_matches=10.0,
        home_advantage=0.25,
        rho=-0.05,
        anchor_attack=(0.0, 0.0),
        anchor_defence=(0.0, 0.0),
        teams=teams,
    )


PARAMS = synthetic_params()


def synthetic_fixtures(scores: dict[str, list[tuple[int, int] | None]]) -> pd.DataFrame:
    """72 group fixtures; `scores[letter]` gives 6 entries (None = unplayed).

    Match order per group: (0,1) (2,3) | (0,2) (1,3) | (0,3) (1,2) — two per
    matchday, mirroring the real schedule's structure.
    """
    pairings = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
    rows = []
    for gi, (letter, teams) in enumerate(sorted(GROUPS.items())):
        for k, (i, j) in enumerate(pairings):
            score = scores.get(letter, [None] * 6)[k]
            rows.append(
                {
                    "date": pd.Timestamp(f"2026-06-{12 + (k // 2) * 4 + gi % 4}"),
                    "home_id": teams[i],
                    "away_id": teams[j],
                    "home_score": None if score is None else score[0],
                    "away_score": None if score is None else score[1],
                    "city": "Testville",
                    "country": "United States",
                    "neutral": True,
                    "high_altitude": False,
                    "played": score is not None,
                }
            )
    df = pd.DataFrame(rows)
    df["home_score"] = df["home_score"].astype(pd.Int64Dtype())
    df["away_score"] = df["away_score"].astype(pd.Int64Dtype())
    return df


def decided_scores(margin_for: int) -> list[tuple[int, int] | None]:
    """All six played: team0 9 pts, team1 6, team2 3, team3 0; team2 beats
    team3 by `margin_for` so thirds are separable across groups.

    Pairing order is (0,1) (2,3) (0,2) (1,3) (0,3) (1,2) — the home side
    (lower index) wins every match.
    """
    return [(3, 0), (margin_for, 0), (3, 0), (3, 0), (3, 0), (3, 0)]


def test_champion_probability_sums_to_one_and_frame_valid() -> None:
    stage = build_group_stage(synthetic_fixtures({}), EMPTY_STATS, REG)
    out = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=7, n_runs=300)
    assert out.reached[:, 6].sum() == 300  # exactly one champion per run
    frame = rankings_frame(out)
    assert len(frame) == 48
    assert frame["p_champion"].sum() == pytest.approx(1.0)
    assert frame["p_r32"].between(0, 1).all()
    assert sorted(frame["rank"]) == list(range(1, 49))


def test_deterministic_under_fixed_seed() -> None:
    stage = build_group_stage(synthetic_fixtures({}), EMPTY_STATS, REG)
    a = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=11, n_runs=150)
    b = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=11, n_runs=150)
    assert np.array_equal(a.reached, b.reached)
    assert np.array_equal(a.group_win, b.group_win)
    c = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=12, n_runs=150)
    assert not np.array_equal(a.reached, c.reached)


def test_decided_group_stage_collapses_to_certainty() -> None:
    """All 72 group matches played -> every team's R32 fate is 0 or 1."""
    scores = {letter: decided_scores(margin_for=i + 1) for i, letter in enumerate("ABCDEFGHIJKL")}
    stage = build_group_stage(synthetic_fixtures(scores), EMPTY_STATS, REG)
    out = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=5, n_runs=200)
    p_r32 = out.reached[:, 1] / 200.0
    assert set(np.round(p_r32, 12)) <= {0.0, 1.0}
    assert int(out.reached[:, 1].sum()) == 32 * 200
    # thirds separate on GF: groups E..L (margins 5..12) advance their third
    for i, t in enumerate(out.teams):
        letter = out.group_of[t]
        pos = GROUPS[letter].index(t)
        expect = 1.0 if pos <= 1 or (pos == 2 and letter >= "E") else 0.0
        assert p_r32[i] == expect, (t, letter, pos)
    # the tracker agrees: every status is decided
    state = tournament_state(stage, NO_ELO, seed=1)
    for ga in state.analyses.values():
        assert all(st.decided for st in ga.statuses.values())


def test_eliminated_team_zero_everywhere_after_result_lands() -> None:
    """Group A's bottom team is alive before MD3, mathematically out after
    the result lands -> 0%% at every stage, exactly (the add-result path
    rebuilds fixtures.parquet; the simulator reads only that)."""
    # MD1+MD2: a1 beat a2/a3, a3 beat a4, a2-a4 drew -> a1 6, a2 4, a3 3, a4 1
    final_scores: list[tuple[int, int] | None] = [(3, 0), (2, 0), (3, 0), (1, 1), (3, 0), (2, 0)]
    before = {"A": [*final_scores[:4], None, None]}  # MD3 not yet played
    stage = build_group_stage(synthetic_fixtures(before), EMPTY_STATS, REG)
    a4 = GROUPS["A"][3]
    out_before = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=3, n_runs=200)
    i4 = out_before.teams.index(a4)
    state_before = tournament_state(stage, NO_ELO, seed=1)
    # 1 point with one match left: beating a1 can still mean 2nd on margins
    assert not state_before.analyses["A"].statuses[a4].eliminated
    assert out_before.reached[i4, 1] > 0  # the MC sees those paths too

    after = {"A": final_scores}  # MD3 lands: a4 finishes bottom on 1 point
    stage2 = build_group_stage(synthetic_fixtures(after), EMPTY_STATS, REG)
    out_after = run_simulation(PARAMS, stage2, BRACKET, ALLOCATION, NO_ELO, seed=3, n_runs=200)
    assert out_after.reached[i4, 1:].sum() == 0  # 0%% everywhere, exactly
    assert out_after.third_qualified[i4] == 0 and out_after.top2[i4] == 0
    state_after = tournament_state(stage2, NO_ELO, seed=1)
    assert state_after.analyses["A"].statuses[a4].eliminated
    # ...and the rest of the group recalculated too
    assert out_after.reached[out_after.teams.index(GROUPS["A"][0]), 1] == 200


def test_md3_dead_rubber_flagged() -> None:
    """Group A after MD2: a1 on 6 (won the h2h vs everyone), a2/a3 on 3, a4
    on 0. MD3 is a1-a4 (dead: a1 secured via h2h even if beaten, a4
    eliminated) and a2-a3 (alive: the loser ends on 3 points and misses the
    best eight). Other groups are complete with 4-point thirds so a 3-point
    third cannot sneak in.
    """
    four_point_third = [(1, 1), (2, 0), (2, 0), (2, 0), (2, 0), (1, 1)]
    scores: dict[str, list[tuple[int, int] | None]] = {
        letter: four_point_third for letter in "BCDEFGHIJKL"
    }
    scores["A"] = [(3, 0), (3, 0), (3, 0), (3, 0), None, None]
    stage = build_group_stage(synthetic_fixtures(scores), EMPTY_STATS, REG)
    state = tournament_state(stage, NO_ELO, seed=1)
    sts = state.analyses["A"].statuses
    a1, a2, a3, a4 = GROUPS["A"]
    assert sts[a1].secured_advance
    assert sts[a4].eliminated
    assert not sts[a2].decided and not sts[a3].decided
    flagged = {(d.home_id, d.away_id) for d in state.dead_rubbers}
    assert flagged == {(a1, a4)}


def test_cross_group_fixture_raises() -> None:
    df = synthetic_fixtures({})
    df.loc[0, "away_id"] = GROUPS["B"][0]
    with pytest.raises(ValueError, match="crosses groups"):
        build_group_stage(df, EMPTY_STATS, REG)


def test_ko_orientation_host_home_advantage() -> None:
    assert _ko_orientation("united_states", "ghana", "United States") == (
        "united_states",
        "ghana",
        True,
    )
    assert _ko_orientation("ghana", "mexico", "Mexico") == ("mexico", "ghana", True)
    assert _ko_orientation("ghana", "japan", "Canada") == ("ghana", "japan", False)
    assert _ko_orientation("canada", "ghana", "United States") == ("canada", "ghana", False)
