"""Seeded Monte Carlo of the remaining tournament (Phase 5.3).

Every remaining match is sampled from the goal engine's correct-score grid
(the latest FITTED params are an input — the simulator never refits); played
matches enter as fact. Group tables use the official tiebreakers
(sim/standings.py); thirds are allocated to R32 slots via FIFA's Annex C
table (sim/bracket.py).

A 90-minute knockout draw is resolved ONLY for advancement (D004) by the
explicit extra-time/penalties model of D024: 30 minutes of extra time as an
independent Poisson mini-match at one third of each side's 90' rate
(strength-weighted conditional on the draw), then a 50/50 penalty shootout.
None of this exists in src/wc26/markets — futures are unbettable (PLAN 5.5).

Host home advantage: a host federation playing a knockout match in its own
country is modelled as the home side; every other knockout match is neutral
(CLAUDE.md invariant; group matches carry their own flag from fixtures).

Pure functions: callers load params/bracket/fixtures and pass them in.
Deterministic for a fixed seed (gate-tested).
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandera.pandas as pa
from numpy.typing import NDArray

from wc26.models.goal_engine import GoalEngineParams, predict_grid
from wc26.sim.bracket import HOST_COUNTRY, Bracket, KnockoutMatch, Slot
from wc26.sim.standings import GroupMatch, Record, rank_group, rank_thirds, records
from wc26.sim.tracker import GroupStage

STAGES = ("group", "r32", "r16", "qf", "sf", "final", "champion")
_ROUND_STAGE = {"r32": 2, "r16": 3, "qf": 4, "sf": 5, "final": 6}
_ET_RATE_FRACTION = 1.0 / 3.0  # 30 of 90 minutes (D024)

RANKINGS_SCHEMA = pa.DataFrameSchema(
    {
        "team_id": pa.Column(str),
        "group": pa.Column(str, pa.Check.isin(list("ABCDEFGHIJKL"))),
        "p_group_win": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_r32": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_r16": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_qf": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_sf": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_final": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "p_champion": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "exp_stage": pa.Column(float, pa.Check.in_range(0.0, 6.0)),
        "rank": pa.Column(int, pa.Check.in_range(1, 48)),
    },
    strict="filter",
    coerce=True,
)


@dataclass(frozen=True)
class SimOutput:
    teams: tuple[str, ...]
    group_of: dict[str, str]
    n_runs: int
    seed: int
    model_version: str
    # reached[i, s] = #runs in which teams[i] reached at least stage s
    reached: NDArray[np.int64]
    group_win: NDArray[np.int64]
    top2: NDArray[np.int64]
    third_qualified: NDArray[np.int64]
    stage_sum: NDArray[np.int64]


class _MatchSampler:
    """Lazily cached correct-score grids + ET lambdas per (home, away, ha)."""

    def __init__(self, params: GoalEngineParams) -> None:
        self._params = params
        self._cache: dict[tuple[str, str, bool], tuple[NDArray[np.float64], int]] = {}

    def dist(self, home: str, away: str, home_adv: bool) -> tuple[NDArray[np.float64], int]:
        key = (home, away, home_adv)
        hit = self._cache.get(key)
        if hit is None:
            grid = predict_grid(self._params, home, away, neutral=not home_adv)
            matrix = np.asarray(grid.grid, dtype=np.float64)
            flat = matrix.ravel() / matrix.sum()
            hit = (np.cumsum(flat), matrix.shape[0])
            self._cache[key] = hit
        return hit

    def lambdas(self, home: str, away: str, home_adv: bool) -> tuple[float, float]:
        p = self._params
        h, a = p.teams[home], p.teams[away]
        ha = p.home_advantage if home_adv else 0.0
        return float(np.exp(h.attack + a.defence + ha)), float(np.exp(a.attack + h.defence))


def _sample_scores(
    cum: NDArray[np.float64], n: int, u: NDArray[np.float64]
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    idx = np.searchsorted(cum, u, side="right")
    return (idx // n).astype(np.int64), (idx % n).astype(np.int64)


def _ko_orientation(team_a: str, team_b: str, country: str) -> tuple[str, str, bool]:
    if HOST_COUNTRY.get(team_a) == country:
        return team_a, team_b, True
    if HOST_COUNTRY.get(team_b) == country:
        return team_b, team_a, True
    return team_a, team_b, False


def _resolve_knockout(
    match: KnockoutMatch,
    team_a: str,
    team_b: str,
    sampler: _MatchSampler,
    rng: np.random.Generator,
) -> tuple[str, str]:
    """(winner, loser) of one knockout match — 90' sample, then D024 ET/pens."""
    home, away, home_adv = _ko_orientation(team_a, team_b, match.country)
    cum, n = sampler.dist(home, away, home_adv)
    hg, ag = _sample_scores(cum, n, np.asarray([rng.random()]))
    if hg[0] != ag[0]:
        return (home, away) if hg[0] > ag[0] else (away, home)
    lam_h, lam_a = sampler.lambdas(home, away, home_adv)
    et_h = int(rng.poisson(lam_h * _ET_RATE_FRACTION))
    et_a = int(rng.poisson(lam_a * _ET_RATE_FRACTION))
    if et_h != et_a:
        return (home, away) if et_h > et_a else (away, home)
    return (home, away) if rng.random() < 0.5 else (away, home)


def _slot_team(
    slot: Slot,
    finishers: Mapping[str, list[str]],
    third_by_group: Mapping[str, str],
    assignment: Mapping[str, str],
    winner_group: str | None,
    results: Mapping[int, tuple[str, str]],
) -> str:
    if slot.kind == "group":
        return finishers[slot.group or ""][int(slot.rank or 0) - 1]
    if slot.kind == "third":
        if winner_group is None:
            raise ValueError("third slot without a group-winner opponent")
        return third_by_group[assignment[winner_group]]
    ref = results[int(slot.ref_match or 0)]
    return ref[0] if slot.kind == "winner" else ref[1]


def run_simulation(
    params: GoalEngineParams,
    stage: GroupStage,
    bracket: Bracket,
    allocation: Mapping[frozenset[str], dict[str, str]],
    elo: Mapping[str, float],
    seed: int,
    n_runs: int,
) -> SimOutput:
    """Simulate the remaining tournament n_runs times; count stages reached."""
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1")
    rng = np.random.default_rng(seed)
    sampler = _MatchSampler(params)
    letters = sorted(stage.groups)
    teams: tuple[str, ...] = tuple(t for g in letters for t in stage.groups[g])
    idx = {t: i for i, t in enumerate(teams)}
    group_of = {t: g for g in letters for t in stage.groups[g]}

    # Vectorized 90' samples for the remaining group matches, in fixed order.
    flat_remaining = [(g, m) for g in letters for m in stage.remaining[g]]
    sampled: list[tuple[NDArray[np.int64], NDArray[np.int64]]] = []
    for _, m in flat_remaining:
        cum, n = sampler.dist(m.home_id, m.away_id, not m.neutral)
        sampled.append(_sample_scores(cum, n, rng.random(n_runs)))
    lots_priority = rng.random((n_runs, len(teams)))

    reached = np.zeros((len(teams), len(STAGES)), dtype=np.int64)
    group_win = np.zeros(len(teams), dtype=np.int64)
    top2 = np.zeros(len(teams), dtype=np.int64)
    third_q = np.zeros(len(teams), dtype=np.int64)
    stage_sum = np.zeros(len(teams), dtype=np.int64)
    reached[:, 0] = n_runs  # everyone is in the tournament

    for r in range(n_runs):
        lots_order = [teams[i] for i in np.argsort(lots_priority[r], kind="stable")]
        finishers: dict[str, list[str]] = {}
        third_by_group: dict[str, str] = {}
        third_records: dict[str, Record] = {}
        all_matches: dict[str, list[GroupMatch]] = {}
        for k, (g, m) in enumerate(flat_remaining):
            hg, ag = sampled[k]
            all_matches.setdefault(g, []).append(
                GroupMatch(m.home_id, m.away_id, int(hg[r]), int(ag[r]))
            )
        for g in letters:
            matches = list(stage.played[g]) + all_matches.get(g, [])
            order = rank_group(matches, stage.groups[g], stage.conduct, elo, lots_order)
            finishers[g] = order
            third = order[2]
            third_by_group[g] = third
            third_records[third] = records(matches, stage.groups[g])[third]
        thirds_ranked = rank_thirds(third_records, stage.conduct, elo, lots_order)
        qualified_thirds = thirds_ranked[:8]
        qualified_letters = frozenset(group_of[t] for t in qualified_thirds)
        assignment = allocation[qualified_letters]

        stage_reached = dict.fromkeys(teams, 0)
        for g in letters:
            group_win[idx[finishers[g][0]]] += 1
            for t in finishers[g][:2]:
                top2[idx[t]] += 1
                stage_reached[t] = 1
        for t in qualified_thirds:
            third_q[idx[t]] += 1
            stage_reached[t] = 1

        results: dict[int, tuple[str, str]] = {}
        for match in bracket.matches:
            winner_group = match.team_a.group if match.team_b.kind == "third" else None
            team_a = _slot_team(match.team_a, finishers, third_by_group, assignment, None, results)
            team_b = _slot_team(
                match.team_b, finishers, third_by_group, assignment, winner_group, results
            )
            winner, loser = _resolve_knockout(match, team_a, team_b, sampler, rng)
            results[match.match_no] = (winner, loser)
            if match.round != "third_place":
                stage_reached[winner] = _ROUND_STAGE[match.round]

        for t, s in stage_reached.items():
            i = idx[t]
            stage_sum[i] += s
            reached[i, 1 : s + 1] += 1

    return SimOutput(
        teams=teams,
        group_of=group_of,
        n_runs=n_runs,
        seed=seed,
        model_version=params.version,
        reached=reached,
        group_win=group_win,
        top2=top2,
        third_qualified=third_q,
        stage_sum=stage_sum,
    )


def rankings_frame(out: SimOutput) -> pd.DataFrame:
    """Per-team rankings table: P(reach stage) columns + expected finish.

    Rank = order by expected exit stage, tie-broken by P(champion) (PLAN 5.3).
    """
    n = float(out.n_runs)
    df = pd.DataFrame(
        {
            "team_id": list(out.teams),
            "group": [out.group_of[t] for t in out.teams],
            "p_group_win": out.group_win / n,
            "p_r32": out.reached[:, 1] / n,
            "p_r16": out.reached[:, 2] / n,
            "p_qf": out.reached[:, 3] / n,
            "p_sf": out.reached[:, 4] / n,
            "p_final": out.reached[:, 5] / n,
            "p_champion": out.reached[:, 6] / n,
            "exp_stage": out.stage_sum / n,
        }
    )
    order = df.sort_values(
        ["exp_stage", "p_champion", "team_id"], ascending=[False, False, True], kind="stable"
    ).reset_index(drop=True)
    order["rank"] = order.index + 1
    return RANKINGS_SCHEMA.validate(order)
