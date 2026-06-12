"""Phase 6.1: played knockout matches consumed as facts (+ KO predict glue).

Built on the same constructed tournament as tests/test_sim_gates.py so
everything runs on a fresh clone with no processed data. Also pins the
extra-time exclusion (D012/D014/D017) on constructed WC26 knockout rows —
the rows the live tournament is about to produce.
"""

import numpy as np
import pandas as pd
import pytest
from test_sim_gates import (
    ALLOCATION,
    BRACKET,
    EMPTY_STATS,
    GROUPS,
    NO_ELO,
    PARAMS,
    REG,
    decided_scores,
    synthetic_fixtures,
)

from wc26.cli import fixture_stage
from wc26.models.goal_engine import predict_grid, prepare_training_data
from wc26.models.prop_features import props_universe
from wc26.sim.bracket import KnockoutMatch
from wc26.sim.mc import run_simulation
from wc26.sim.tracker import KnockoutFact, build_group_stage, knockout_facts

KO_START = pd.Timestamp(min(m.date for m in BRACKET.matches))


def first_all_group_r32() -> KnockoutMatch:
    """First R32 match whose both slots are group finishers (no third/winner)."""
    for m in BRACKET.matches:
        if m.round == "r32" and m.team_a.kind == "group" and m.team_b.kind == "group":
            return m
    raise AssertionError("bracket has no all-group R32 match")


def slot_team(match: KnockoutMatch) -> tuple[str, str]:
    """Resolve both group slots under the decided_scores finishing order."""
    teams = []
    for slot in (match.team_a, match.team_b):
        assert slot.group is not None and slot.rank is not None
        teams.append(GROUPS[slot.group][slot.rank - 1])
    return teams[0], teams[1]


def decided_groups() -> dict[str, list[tuple[int, int] | None]]:
    return {letter: decided_scores(margin_for=i + 1) for i, letter in enumerate("ABCDEFGHIJKL")}


def ko_fixture_row(
    home: str, away: str, date: pd.Timestamp, score: tuple[int, int] | None
) -> dict[str, object]:
    return {
        "date": date,
        "home_id": home,
        "away_id": away,
        "home_score": None if score is None else score[0],
        "away_score": None if score is None else score[1],
        "city": "Testville",
        "country": "United States",
        "neutral": True,
        "high_altitude": False,
        "played": score is not None,
    }


def with_ko_rows(base: pd.DataFrame, rows: list[dict[str, object]]) -> pd.DataFrame:
    df = pd.concat([base, pd.DataFrame(rows)], ignore_index=True)
    df["home_score"] = df["home_score"].astype(pd.Int64Dtype())
    df["away_score"] = df["away_score"].astype(pd.Int64Dtype())
    return df


# ---------------------------------------------------------------- tracker


def test_build_group_stage_excludes_knockout_rows_with_start() -> None:
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    fixtures = with_ko_rows(
        synthetic_fixtures(decided_groups()),
        [ko_fixture_row(team_a, team_b, pd.Timestamp(match.date), (2, 1))],
    )
    stage = build_group_stage(fixtures, EMPTY_STATS, REG, knockout_start=KO_START)
    assert sum(len(p) for p in stage.played.values()) == 72
    # without knockout_start the same table must still fail loudly
    with pytest.raises(ValueError, match="crosses groups"):
        build_group_stage(fixtures, EMPTY_STATS, REG)


def test_knockout_facts_decisive_and_unplayed() -> None:
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    fixtures = with_ko_rows(
        synthetic_fixtures(decided_groups()),
        [
            ko_fixture_row(team_a, team_b, pd.Timestamp(match.date), (1, 3)),
            # an unplayed KO fixture carries no information -> ignored
            ko_fixture_row(GROUPS["C"][0], GROUPS["D"][1], KO_START, None),
        ],
    )
    facts = knockout_facts(fixtures, EMPTY_STATS, REG, knockout_start=KO_START)
    assert len(facts) == 1
    assert facts[0].winner_id == team_b
    assert facts[0].pair == frozenset((team_a, team_b))


def test_knockout_facts_pens_winner_from_match_stats() -> None:
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    date = pd.Timestamp(match.date)
    fixtures = with_ko_rows(
        synthetic_fixtures(decided_groups()), [ko_fixture_row(team_a, team_b, date, (1, 1))]
    )
    stats = pd.DataFrame(
        {
            "date": [date],
            "home_id": [team_a],
            "away_id": [team_b],
            "shootout_winner_id": [team_a],
        }
    )
    facts = knockout_facts(fixtures, stats, REG, knockout_start=KO_START)
    assert facts[0].winner_id == team_a
    # level score with no shootout winner anywhere -> loud failure, never a guess
    with pytest.raises(ValueError, match="penalties"):
        knockout_facts(fixtures, EMPTY_STATS, REG, knockout_start=KO_START)


# ---------------------------------------------------------------- simulator


def test_fact_winner_advances_in_every_run() -> None:
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    # the fact's winner is the side the engine would normally make the dog
    fact = KnockoutFact(
        date=pd.Timestamp(match.date),
        home_id=team_a,
        away_id=team_b,
        home_score=0,
        away_score=1,
        winner_id=team_b,
    )
    stage = build_group_stage(
        synthetic_fixtures(decided_groups()), EMPTY_STATS, REG, knockout_start=KO_START
    )
    out = run_simulation(
        PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=9, n_runs=150, ko_facts=(fact,)
    )
    i_win, i_lose = out.teams.index(team_b), out.teams.index(team_a)
    assert out.reached[i_win, 2] == 150  # winner reaches R16 in every run
    assert out.reached[i_lose, 2] == 0  # loser exactly never
    # without the fact the same seed lets both sides through sometimes
    free = run_simulation(PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=9, n_runs=150)
    assert free.reached[i_win, 2] > 0 and free.reached[i_lose, 2] > 0


def test_facts_deterministic_and_gates_unaffected() -> None:
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    fact = KnockoutFact(
        date=pd.Timestamp(match.date),
        home_id=team_a,
        away_id=team_b,
        home_score=2,
        away_score=0,
        winner_id=team_a,
    )
    stage = build_group_stage(
        synthetic_fixtures(decided_groups()), EMPTY_STATS, REG, knockout_start=KO_START
    )
    a = run_simulation(
        PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=11, n_runs=100, ko_facts=(fact,)
    )
    b = run_simulation(
        PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=11, n_runs=100, ko_facts=(fact,)
    )
    assert np.array_equal(a.reached, b.reached)
    assert a.reached[:, 6].sum() == 100  # still exactly one champion per run


def test_unmatched_fact_raises() -> None:
    """A fact whose pair never meets in the resolved bracket must fail loudly."""
    # under decided_scores, two group winners from R32 matches that don't pair
    fact = KnockoutFact(
        date=pd.Timestamp(BRACKET.matches[0].date),
        home_id=GROUPS["A"][0],
        away_id=GROUPS["B"][0],
        home_score=1,
        away_score=0,
        winner_id=GROUPS["A"][0],
    )
    stage = build_group_stage(
        synthetic_fixtures(decided_groups()), EMPTY_STATS, REG, knockout_start=KO_START
    )
    with pytest.raises(ValueError, match="never matched a bracket slot"):
        run_simulation(
            PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=3, n_runs=5, ko_facts=(fact,)
        )


def test_facts_with_unplayed_group_fixtures_raise() -> None:
    fact = KnockoutFact(
        date=pd.Timestamp(BRACKET.matches[0].date),
        home_id=GROUPS["A"][0],
        away_id=GROUPS["B"][1],
        home_score=1,
        away_score=0,
        winner_id=GROUPS["A"][0],
    )
    stage = build_group_stage(synthetic_fixtures({}), EMPTY_STATS, REG, knockout_start=KO_START)
    with pytest.raises(ValueError, match="still unplayed"):
        run_simulation(
            PARAMS, stage, BRACKET, ALLOCATION, NO_ELO, seed=3, n_runs=5, ko_facts=(fact,)
        )


# ---------------------------------------------------------------- predict glue


def test_fixture_stage_group_vs_knockout() -> None:
    a1, a2, _a3, a4 = GROUPS["A"]
    fixtures = with_ko_rows(
        synthetic_fixtures(decided_groups()),
        [ko_fixture_row(a1, GROUPS["B"][1], KO_START, None)],
    )
    md1 = fixture_stage(fixtures, a1, a2, pd.Timestamp("2026-06-12"), KO_START)
    assert md1 == (1, False)
    # MD3 of group A in the synthetic calendar (k=4 -> 12 + 2*4 = June 20)
    md3 = fixture_stage(fixtures, a1, a4, pd.Timestamp("2026-06-20"), KO_START)
    assert md3 == (3, False)
    # a knockout-day fixture: no matchday, knockout=True — and its presence in
    # the table must not have inflated the group matchday counts above
    ko = fixture_stage(fixtures, a1, GROUPS["B"][1], KO_START, KO_START)
    assert ko == (0, True)


def test_knockout_1x2_includes_draw() -> None:
    """Risk register: knockout 90' probabilities keep the draw (D004).

    The goal engine has no stage parameter — the exact same grid prices
    group and knockout matches — so a knockout pairing's 1X2 must carry
    real draw mass; only the simulator's advancement layer resolves it.
    """
    match = first_all_group_r32()
    team_a, team_b = slot_team(match)
    grid = predict_grid(PARAMS, team_a, team_b, neutral=True)
    p_home, p_draw, p_away = (float(p) for p in grid.home_draw_away)
    assert p_draw > 0.05
    assert p_home + p_draw + p_away == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------- extra time (D012/D014/D017)


def _wc26_ko_results_row(home: str, away: str, date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp(date)],
            "home_id": [home],
            "away_id": [away],
            "home_score": [2],  # 120' score as stored upstream (D012)
            "away_score": [1],
            "tournament": ["FIFA World Cup"],
            "tier": ["world_cup"],
            "neutral": [True],
        }
    )


def test_prepare_training_data_drops_wc26_et_knockout_row() -> None:
    """A WC26 KO match flagged extra_time must never train the goal engine."""
    results = pd.concat(
        [
            _wc26_ko_results_row("argentina", "mexico", "2026-06-29"),
            _wc26_ko_results_row("france", "ghana", "2026-06-30"),
        ],
        ignore_index=True,
    )
    # ESPN dates the ET match one day off (UTC vs local, D013) — must still match
    stats = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-28")],
            "home_id": ["argentina"],
            "away_id": ["mexico"],
            "extra_time": [True],
        }
    )
    train = prepare_training_data(
        results, stats, cutoff=pd.Timestamp("2026-07-04"), window_years=10
    )
    assert len(train) == 1
    assert train.iloc[0]["home_id"] == "france"  # the 90' match survived


def test_props_universe_drops_wc26_et_knockout_row() -> None:
    def stats_row(home: str, away: str, extra_time: bool) -> dict[str, object]:
        return {
            "date": pd.Timestamp("2026-06-29"),
            "tournament": "FIFA World Cup",
            "home_id": home,
            "away_id": away,
            "home_score": 2,
            "away_score": 1,
            "extra_time": extra_time,
            "referee": "Ref A",
            **{
                f"{stat}_{side}": 5.0
                for stat in ("corners", "yellows", "reds", "fouls", "shots")
                for side in ("home", "away")
            },
        }

    stats = pd.DataFrame(
        [stats_row("argentina", "mexico", True), stats_row("france", "ghana", False)]
    )
    results = pd.concat(
        [
            _wc26_ko_results_row("argentina", "mexico", "2026-06-29"),
            _wc26_ko_results_row("france", "ghana", "2026-06-29"),
        ],
        ignore_index=True,
    )
    universe = props_universe(stats, results)
    assert len(universe) == 1
    assert universe.iloc[0]["home_id"] == "france"
