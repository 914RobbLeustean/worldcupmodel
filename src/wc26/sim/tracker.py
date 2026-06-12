"""Group-stage tracker: fixtures/match_stats DataFrames -> group state (5.1).

This is the pandera-validated DataFrame boundary in front of the pure
standings code. It produces:
- per-group played matches / remaining fixtures (with the neutral flag the
  goal engine needs),
- team conduct scores from real card counts (D023 approximation),
- the qualification analysis incl. MD3 dead-rubber flags.

The group stage is identified by date: fixtures on/after `knockout_start`
(the bracket's first R32 date — callers read it off the loaded bracket) are
knockout rows and are consumed separately as KnockoutFact records
(Phase 6.1). Within the group window, both teams of a fixture must be in
the same group (registry) — a cross-group fixture there means corrupted
data and must fail loudly. When no knockout_start is given (legacy/test
callers), ANY cross-group fixture raises, so knockout results can never be
silently ignored.
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


@dataclass(frozen=True)
class KnockoutFact:
    """A played WC26 knockout match, consumed by the simulator as fact.

    Scores are as stored (120' totals for extra-time matches, D012) — they
    identify the ADVANCING team only, never a 90' price. `winner_id` is
    always resolved: from the score when decisive, from the ESPN shootout
    winner when level (pens).
    """

    date: pd.Timestamp
    home_id: str
    away_id: str
    home_score: int
    away_score: int
    winner_id: str

    @property
    def pair(self) -> frozenset[str]:
        return frozenset((self.home_id, self.away_id))


def build_group_stage(
    fixtures: pd.DataFrame,
    match_stats: pd.DataFrame,
    reg: TeamRegistry,
    knockout_start: pd.Timestamp | None = None,
) -> GroupStage:
    """Split WC26 fixtures into played/remaining per group + conduct scores.

    Rows on/after `knockout_start` are knockout matches and are excluded —
    consume them via `knockout_facts`. Conduct only ever counts group
    matches (FIFA art. 13 ranks GROUP conduct).
    """
    fixtures = FIXTURES_SCHEMA.validate(fixtures).sort_values(
        ["date", "home_id", "away_id"], kind="stable"
    )
    if knockout_start is not None:
        fixtures = fixtures[fixtures["date"] < knockout_start]
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
                f"fixture {home} v {away} crosses groups {g_home}/{g_away} inside the "
                f"group-stage window — a knockout row here means knockout_start was "
                f"not passed (or is wrong); knockout matches are consumed via "
                f"knockout_facts(), never silently ignored"
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


def knockout_facts(
    fixtures: pd.DataFrame,
    match_stats: pd.DataFrame,
    reg: TeamRegistry,
    knockout_start: pd.Timestamp,
) -> tuple[KnockoutFact, ...]:
    """Played knockout fixtures as facts for the simulator.

    Unplayed knockout rows carry nothing the bracket + group results don't
    already determine, so they are ignored. A played row with a level score
    was decided on penalties (D012: stored scores include ET, shootouts stay
    level); its advancing team comes from match_stats.shootout_winner_id —
    missing means the scrape predates the column or ESPN failed us, and we
    raise rather than guess a coin flip that already landed.
    """
    fixtures = FIXTURES_SCHEMA.validate(fixtures)
    ko = fixtures[(fixtures["date"] >= knockout_start) & fixtures["played"]].sort_values(
        ["date", "home_id"], kind="stable"
    )
    facts: list[KnockoutFact] = []
    rows = zip(
        ko["date"], ko["home_id"], ko["away_id"], ko["home_score"], ko["away_score"], strict=True
    )
    for raw_date, raw_home, raw_away, raw_home_score, raw_away_score in rows:
        home, away = str(raw_home), str(raw_away)
        missing = [t for t in (home, away) if t not in reg.wc26_ids]
        if missing:  # strict resolution: knockout participants must be registered
            raise ValueError(f"knockout fixture {home} v {away}: unregistered team(s) {missing}")
        home_score, away_score = int(raw_home_score), int(raw_away_score)
        date = pd.Timestamp(raw_date)
        if home_score != away_score:
            winner = home if home_score > away_score else away
        else:
            winner = _shootout_winner(match_stats, date, home, away)
        facts.append(
            KnockoutFact(
                date=date,
                home_id=home,
                away_id=away,
                home_score=home_score,
                away_score=away_score,
                winner_id=winner,
            )
        )
    return tuple(facts)


def _shootout_winner(match_stats: pd.DataFrame, date: pd.Timestamp, home: str, away: str) -> str:
    """Advancing team of a pens knockout match, from the stats table (±1 day, D013)."""
    if not match_stats.empty and "shootout_winner_id" in match_stats.columns:
        near = (match_stats["date"] - date).abs() <= pd.Timedelta(days=1)
        pair = match_stats["home_id"].isin([home, away]) & match_stats["away_id"].isin([home, away])
        hit = match_stats[near & pair]
        if len(hit) == 1:
            winner = hit.iloc[0]["shootout_winner_id"]
            if pd.notna(winner) and str(winner) in (home, away):
                return str(winner)
    raise ValueError(
        f"knockout match {home} v {away} on {date.date()} ended level — decided on "
        f"penalties, but no shootout_winner_id in match_stats. Re-run `wc26 data "
        f"scrape --tournament wc2026`, or add the row to data/manual/stats_patch.csv "
        f"with shootout_winner_id set"
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
