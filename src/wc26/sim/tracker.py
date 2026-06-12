"""Group-stage tracker: fixtures/match_stats DataFrames -> group state (5.1).

This is the pandera-validated DataFrame boundary in front of the pure
standings code. It produces:
- per-group played matches / remaining fixtures (with the neutral flag the
  goal engine needs),
- team conduct scores from real card counts (D023 approximation),
- the qualification analysis incl. MD3 dead-rubber flags.

The group stage is identified structurally: both teams of a fixture must be
in the same group (registry) — a cross-group WC26 fixture means knockout
results have started landing upstream, which Phase 5 does not consume
(knockout facts are a Phase 6 task) and must fail loudly here.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from wc26.data.results import FIXTURES_SCHEMA
from wc26.data.teams import TeamRegistry
from wc26.sim.standings import (
    GroupAnalysis,
    GroupMatch,
    analyse_group,
    resolve_cross_group,
)


@dataclass(frozen=True)
class RemainingMatch:
    home_id: str
    away_id: str
    neutral: bool
    matchday: int


@dataclass(frozen=True)
class GroupStage:
    """Everything the simulator/tracker needs about the 12 groups."""

    groups: dict[str, tuple[str, ...]]  # letter -> 4 team ids (yaml order)
    played: dict[str, tuple[GroupMatch, ...]]
    remaining: dict[str, tuple[RemainingMatch, ...]]
    conduct: dict[str, float]  # team conduct score from real matches (<= 0)


def build_group_stage(
    fixtures: pd.DataFrame, match_stats: pd.DataFrame, reg: TeamRegistry
) -> GroupStage:
    """Split WC26 fixtures into played/remaining per group + conduct scores."""
    fixtures = FIXTURES_SCHEMA.validate(fixtures).sort_values(
        ["date", "home_id", "away_id"], kind="stable"
    )
    groups: dict[str, tuple[str, ...]] = {}
    for letter in sorted({t.group for t in reg.teams.values()}):
        groups[letter] = tuple(t.id for t in reg.group(letter))
        if len(groups[letter]) != 4:
            raise ValueError(f"group {letter} has {len(groups[letter])} teams in teams.yaml")

    played: dict[str, list[GroupMatch]] = {g: [] for g in groups}
    remaining: dict[str, list[RemainingMatch]] = {g: [] for g in groups}
    seen: dict[str, int] = dict.fromkeys(groups, 0)
    rows = zip(
        fixtures["home_id"],
        fixtures["away_id"],
        fixtures["home_score"],
        fixtures["away_score"],
        fixtures["neutral"],
        fixtures["played"],
        strict=True,
    )
    for home_raw, away_raw, home_score, away_score, neutral, was_played in rows:
        home, away = str(home_raw), str(away_raw)
        g_home, g_away = reg[home].group, reg[away].group
        if g_home != g_away:
            raise ValueError(
                f"fixture {home} v {away} crosses groups {g_home}/{g_away} — knockout "
                f"results in fixtures.parquet are not consumed by Phase 5 (see D009)"
            )
        matchday = seen[g_home] // 2 + 1  # 2 matches per group per matchday
        seen[g_home] += 1
        if bool(was_played):
            played[g_home].append(GroupMatch(home, away, int(home_score), int(away_score)))
        else:
            remaining[g_home].append(RemainingMatch(home, away, bool(neutral), matchday))
    counts = {g: len(played[g]) + len(remaining[g]) for g in groups}
    if any(c != 6 for c in counts.values()):
        raise ValueError(f"every group must have 6 fixtures, got {counts}")

    return GroupStage(
        groups=groups,
        played={g: tuple(v) for g, v in played.items()},
        remaining={g: tuple(v) for g, v in remaining.items()},
        conduct=_conduct_scores(fixtures, match_stats, reg),
    )


def _conduct_scores(
    fixtures: pd.DataFrame, match_stats: pd.DataFrame, reg: TeamRegistry
) -> dict[str, float]:
    """Team conduct from real WC26 card counts: -1/yellow, -4/red (D023).

    Stats rows are matched to group fixtures by team pair within ±1 day
    (D013). Missing counts contribute 0 — fail-soft is correct here, conduct
    is the second-to-last tiebreaker.
    """
    conduct: dict[str, float] = dict.fromkeys(reg.wc26_ids, 0.0)
    if match_stats.empty:
        return conduct
    pairs = {
        frozenset((str(r.home_id), str(r.away_id))): pd.Timestamp(str(r.date))
        for r in fixtures.itertuples(index=False)
        if bool(r.played)
    }
    rows = zip(
        match_stats["date"],
        match_stats["home_id"],
        match_stats["away_id"],
        match_stats["yellows_home"],
        match_stats["yellows_away"],
        match_stats["reds_home"],
        match_stats["reds_away"],
        strict=True,
    )
    for date_raw, home, away, yh, ya, rh, ra in rows:
        key = frozenset((str(home), str(away)))
        date = pairs.get(key)
        if date is None or abs(pd.Timestamp(str(date_raw)) - date) > pd.Timedelta(days=1):
            continue
        for team, yellows, reds in ((str(home), yh, rh), (str(away), ya, ra)):
            y = float(yellows) if pd.notna(yellows) else 0.0
            r = float(reds) if pd.notna(reds) else 0.0
            conduct[team] = conduct.get(team, 0.0) - y - 4.0 * r
    return conduct


@dataclass(frozen=True)
class DeadRubber:
    group: str
    matchday: int
    home_id: str
    away_id: str


@dataclass(frozen=True)
class TournamentState:
    analyses: dict[str, GroupAnalysis]  # cross-group resolved
    dead_rubbers: tuple[DeadRubber, ...]


def tournament_state(stage: GroupStage, elo: Mapping[str, float], seed: int) -> TournamentState:
    """Full qualification analysis + MD3 dead rubbers.

    A remaining MD3 match is a dead rubber when BOTH teams' advancement is
    already decided (secured or eliminated) — qualification is not at stake,
    historically the softest lines. Bracket-slot routing (1st vs 2nd) may
    still matter for secured teams; the per-team flags shown alongside make
    that visible.
    """
    rng = np.random.default_rng(seed)
    analyses: dict[str, GroupAnalysis] = {}
    for letter, teams in stage.groups.items():
        lots = [teams[i] for i in rng.permutation(len(teams))]
        analyses[letter] = analyse_group(
            group=letter,
            played=stage.played[letter],
            teams=teams,
            remaining=[(m.home_id, m.away_id) for m in stage.remaining[letter]],
            conduct=stage.conduct,
            elo=elo,
            lots_order=lots,
        )
    resolved = resolve_cross_group(analyses)

    dead: list[DeadRubber] = []
    for letter, ga in resolved.items():
        for m in stage.remaining[letter]:
            if (
                m.matchday == 3
                and ga.statuses[m.home_id].decided
                and ga.statuses[m.away_id].decided
            ):
                dead.append(DeadRubber(letter, m.matchday, m.home_id, m.away_id))
    return TournamentState(analyses=resolved, dead_rubbers=tuple(dead))
