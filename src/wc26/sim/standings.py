"""Group-stage state: standings, official tiebreakers, qualification status.

Tiebreakers implement the FIFA World Cup 2026 Regulations (May 2025 PDF,
art. 13) EXACTLY as published — which differs from the 2018/2022 procedure:
head-to-head among the tied teams comes FIRST, before overall goal
difference (D023):

  points, then for teams equal on points:
  Step 1  a) h2h points  b) h2h GD  c) h2h goals scored (among tied teams)
  Step 2  re-apply a-c among the teams still tied if step 1 separated
          anyone; once it no longer does: d) overall GD  e) overall GF
          f) team conduct score (cards)
  Step 3  g/h) FIFA/Coca-Cola World Ranking — proxied here by as-of Elo
          (D023); a residual exact tie falls to `lots_order` (drawing of
          lots, seeded by the caller).

The twelve third-placed teams rank on points / GD / GF / conduct / FIFA
ranking (art. 13 last section, same proxies); the first eight qualify.

Conduct score: -1 per yellow, -4 per red (our sources carry yellow and red
COUNTS only, so the -3 second-yellow and -5 yellow+red grades are not
distinguishable; D023). Simulated matches contribute 0.

Qualification analysis (`analyse_group` + `resolve_cross_group`) enumerates
all 3^k completions of each group's remaining matches. Score margins are
unbounded, so comparisons that depend on a free margin resolve for/against
the team under test (optimistic for `can_*`, adversarial for `secured_*`);
cross-group third-place comparisons are exact at the points level under the
same convention (D024). The Monte Carlo (sim/mc.py) stays the authoritative
source of probabilities; these flags are operational labels.

Pure functions, no I/O (CLAUDE.md).
"""

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import NamedTuple


class GroupMatch(NamedTuple):
    home_id: str
    away_id: str
    home_goals: int
    away_goals: int


class Record(NamedTuple):
    points: int
    gd: int
    gf: int


def records(matches: Iterable[GroupMatch], teams: Sequence[str]) -> dict[str, Record]:
    """Points / goal difference / goals scored per team over `matches`."""
    pts = dict.fromkeys(teams, 0)
    gf = dict.fromkeys(teams, 0)
    ga = dict.fromkeys(teams, 0)
    for m in matches:
        gf[m.home_id] += m.home_goals
        ga[m.home_id] += m.away_goals
        gf[m.away_id] += m.away_goals
        ga[m.away_id] += m.home_goals
        if m.home_goals > m.away_goals:
            pts[m.home_id] += 3
        elif m.home_goals < m.away_goals:
            pts[m.away_id] += 3
        else:
            pts[m.home_id] += 1
            pts[m.away_id] += 1
    return {t: Record(pts[t], gf[t] - ga[t], gf[t]) for t in teams}


def _grouped_desc(items: Sequence[str], key: Mapping[str, tuple[float, ...]]) -> list[list[str]]:
    """Partition `items` into classes of equal key, ordered by key descending."""
    ordered = sorted(items, key=lambda t: key[t], reverse=True)
    classes: list[list[str]] = []
    for t in ordered:
        if classes and key[classes[-1][0]] == key[t]:
            classes[-1].append(t)
        else:
            classes.append([t])
    return classes


def _order_tied(
    tied: Sequence[str],
    matches: Sequence[GroupMatch],
    overall: Mapping[str, Record],
    conduct: Mapping[str, float],
    elo: Mapping[str, float],
    lots_order: Sequence[str],
) -> list[str]:
    """Article 13 steps 1-3 for a set of teams equal on points."""
    tied_set = set(tied)
    h2h = records([m for m in matches if m.home_id in tied_set and m.away_id in tied_set], tied)
    classes = _grouped_desc(tied, {t: tuple(map(float, h2h[t])) for t in tied})
    if len(classes) > 1:
        # Step 1 separated someone; step 2 re-applies a-c among each still-tied
        # subset (matches between the remaining teams only).
        out: list[str] = []
        for cls in classes:
            if len(cls) == 1:
                out.extend(cls)
            else:
                out.extend(_order_tied(cls, matches, overall, conduct, elo, lots_order))
        return out
    # h2h separates nobody: d) overall GD, e) overall GF, f) conduct,
    # g/h) FIFA-ranking proxy (Elo), then drawing of lots — no restart.
    lots_rank = {t: float(-lots_order.index(t)) for t in tied}
    key = {
        t: (
            float(overall[t].gd),
            float(overall[t].gf),
            float(conduct.get(t, 0.0)),
            float(elo.get(t, 0.0)),
            lots_rank[t],
        )
        for t in tied
    }
    return sorted(tied, key=lambda t: key[t], reverse=True)


def rank_group(
    matches: Sequence[GroupMatch],
    teams: Sequence[str],
    conduct: Mapping[str, float],
    elo: Mapping[str, float],
    lots_order: Sequence[str],
) -> list[str]:
    """Final group order (best first) under the official 2026 tiebreakers.

    `lots_order` must contain every team in `teams` (earlier = wins a drawing
    of lots); the caller decides whether it is a seeded shuffle (live
    standings, Monte Carlo) or a deliberate bias (qualification analysis).
    """
    missing = set(teams) - set(lots_order)
    if missing:
        raise ValueError(f"lots_order is missing teams: {sorted(missing)}")
    overall = records(matches, teams)
    out: list[str] = []
    for cls in _grouped_desc(teams, {t: (float(overall[t].points),) for t in teams}):
        if len(cls) == 1:
            out.extend(cls)
        else:
            out.extend(_order_tied(cls, matches, overall, conduct, elo, lots_order))
    return out


def rank_thirds(
    third_records: Mapping[str, Record],
    conduct: Mapping[str, float],
    elo: Mapping[str, float],
    lots_order: Sequence[str],
) -> list[str]:
    """Rank the twelve third-placed teams; the first eight qualify (art. 13)."""
    lots_rank = {t: float(-lots_order.index(t)) for t in third_records}
    return sorted(
        third_records,
        key=lambda t: (
            float(third_records[t].points),
            float(third_records[t].gd),
            float(third_records[t].gf),
            float(conduct.get(t, 0.0)),
            float(elo.get(t, 0.0)),
            lots_rank[t],
        ),
        reverse=True,
    )


# --- qualification analysis (exact points-level enumeration, D024) ---------

_BIG = 99  # an "unbounded margin" stand-in; dwarfs any real goal difference


def _completion_scores(
    outcomes: Sequence[int],
    remaining: Sequence[tuple[str, str]],
    favored: str | None,
    adverse: bool,
) -> list[GroupMatch]:
    """Concrete scores for one W/D/L completion (0=home win, 1=draw, 2=away).

    Margins implement the D024 convention: with `adverse=False` the favored
    team wins by _BIG and everyone else by 1 (best case for `favored`); with
    `adverse=True` the favored team wins by 1 and rivals by _BIG.
    """
    scores: list[GroupMatch] = []
    for (home, away), out in zip(remaining, outcomes, strict=True):
        if out == 1:
            scores.append(GroupMatch(home, away, 0, 0))
            continue
        winner = home if out == 0 else away
        favored_wins = winner == favored
        margin = (1 if favored_wins else _BIG) if adverse else (_BIG if favored_wins else 1)
        if out == 0:
            scores.append(GroupMatch(home, away, margin, 0))
        else:
            scores.append(GroupMatch(home, away, 0, margin))
    return scores


class _Envelope(NamedTuple):
    best_rank: int  # over all completions, optimistic margins + lots
    worst_rank: int  # over all completions, adversarial margins + lots
    best_third_pts: int  # max points held when finishing exactly 3rd (optimistic); -1 if never
    worst_third_pts: int  # min points held when finishing exactly 3rd (adversarial); large if never


@dataclass(frozen=True)
class TeamStatus:
    team_id: str
    group: str
    played: int
    points: int
    gd: int
    gf: int
    rank_now: int
    can_top2: bool
    secured_top2: bool
    can_advance: bool
    secured_advance: bool

    @property
    def eliminated(self) -> bool:
        return not self.can_advance

    @property
    def decided(self) -> bool:
        return self.secured_advance or self.eliminated


@dataclass(frozen=True)
class GroupAnalysis:
    group: str
    order_now: list[str]
    statuses: dict[str, TeamStatus]
    envelopes: dict[str, _Envelope]
    min_third_points: int  # bounds on the eventual 3rd-ranked team's points
    max_third_points: int
    complete: bool
    third_profile: Record | None  # exact (pts, gd, gf) of the third when complete


def _rank_points_under(
    team: str,
    outcomes: Sequence[int],
    played: Sequence[GroupMatch],
    teams: Sequence[str],
    remaining: Sequence[tuple[str, str]],
    conduct: Mapping[str, float],
    adverse: bool,
) -> tuple[int, int]:
    """(rank, points) of `team` for one completion, ties resolved per D024."""
    scores = list(played) + _completion_scores(outcomes, remaining, team, adverse)
    others = [t for t in teams if t != team]
    lots = [*others, team] if adverse else [team, *others]
    order = rank_group(scores, teams, conduct, elo={}, lots_order=lots)
    return order.index(team) + 1, records(scores, teams)[team].points


def analyse_group(
    group: str,
    played: Sequence[GroupMatch],
    teams: Sequence[str],
    remaining: Sequence[tuple[str, str]],
    conduct: Mapping[str, float],
    elo: Mapping[str, float],
    lots_order: Sequence[str],
) -> GroupAnalysis:
    """Per-team qualification envelope from enumerating all 3^k completions.

    `can_advance` / `secured_advance` are left False here — they need the
    other groups' third-place bounds; `resolve_cross_group` fills them.
    """
    if len(teams) != 4:
        raise ValueError(f"group {group}: expected 4 teams, got {len(teams)}")
    overall = records(played, teams)
    order_now = rank_group(played, teams, conduct, elo, lots_order)
    completions = list(itertools.product((0, 1, 2), repeat=len(remaining)))

    envelopes: dict[str, _Envelope] = {}
    min3, max3 = 10**9, -1
    for outcomes in completions:
        scores = list(played) + _completion_scores(outcomes, remaining, None, False)
        pts3 = sorted((r.points for r in records(scores, teams).values()), reverse=True)[2]
        min3, max3 = min(min3, pts3), max(max3, pts3)
    for team in teams:
        best_rank, worst_rank = 5, 0
        best_third_pts, worst_third_pts = -1, 10**9
        for outcomes in completions:
            opt_rank, opt_pts = _rank_points_under(
                team, outcomes, played, teams, remaining, conduct, adverse=False
            )
            pes_rank, pes_pts = _rank_points_under(
                team, outcomes, played, teams, remaining, conduct, adverse=True
            )
            best_rank = min(best_rank, opt_rank)
            worst_rank = max(worst_rank, pes_rank)
            if opt_rank == 3:
                best_third_pts = max(best_third_pts, opt_pts)
            if pes_rank == 3:
                worst_third_pts = min(worst_third_pts, pes_pts)
        envelopes[team] = _Envelope(best_rank, worst_rank, best_third_pts, worst_third_pts)

    matches_played = {t: sum(1 for m in played if t in (m.home_id, m.away_id)) for t in teams}
    statuses = {
        team: TeamStatus(
            team_id=team,
            group=group,
            played=matches_played[team],
            points=overall[team].points,
            gd=overall[team].gd,
            gf=overall[team].gf,
            rank_now=order_now.index(team) + 1,
            can_top2=envelopes[team].best_rank <= 2,
            secured_top2=envelopes[team].worst_rank <= 2,
            can_advance=False,
            secured_advance=False,
        )
        for team in teams
    }
    complete = not remaining
    return GroupAnalysis(
        group=group,
        order_now=order_now,
        statuses=statuses,
        envelopes=envelopes,
        min_third_points=min3,
        max_third_points=max3,
        complete=complete,
        third_profile=overall[order_now[2]] if complete else None,
    )


def _rivals_above(
    own: GroupAnalysis, others: Sequence[GroupAnalysis], pts: int, pessimistic: bool
) -> int:
    """How many other groups' thirds rank above our third (D024 convention).

    Equal-points comparisons hinge on goal difference: while either group has
    matches left, margins are free, so a tie resolves for us (optimistic) or
    against us (pessimistic). Once BOTH groups are complete, the profiles are
    fixed and (pts, gd, gf) compares exactly; residual full ties fall to
    conduct / FIFA-ranking, treated pessimistically only when securing.
    """
    count = 0
    for g in others:
        if g.complete and own.complete and own.third_profile is not None:
            rival = g.third_profile
            assert rival is not None
            ours = (pts, own.third_profile.gd, own.third_profile.gf)
            count += tuple(rival) >= ours if pessimistic else tuple(rival) > ours
        elif g.complete and g.third_profile is not None:
            rival_pts = g.third_profile.points
            count += rival_pts >= pts if pessimistic else rival_pts > pts
        else:
            bound = g.max_third_points if pessimistic else g.min_third_points
            count += bound >= pts if pessimistic else bound > pts
    return count


def resolve_cross_group(analyses: Mapping[str, GroupAnalysis]) -> dict[str, GroupAnalysis]:
    """Fill can_advance / secured_advance using the other groups' thirds.

    Eight of twelve thirds advance, so a third-placed team misses out only
    when >= 8 other thirds rank above it (`_rivals_above` for the comparison
    rules).
    """
    out: dict[str, GroupAnalysis] = {}
    for letter, ga in analyses.items():
        others = [g for k, g in analyses.items() if k != letter]
        statuses: dict[str, TeamStatus] = {}
        for team, st in ga.statuses.items():
            env = ga.envelopes[team]
            can_via_third = (
                env.best_third_pts >= 0
                and _rivals_above(ga, others, env.best_third_pts, pessimistic=False) <= 7
            )
            # worst_rank == 3 implies some adversarial completion ranked the
            # team exactly 3rd, so worst_third_pts is set in that case.
            secured = env.worst_rank <= 2 or (
                env.worst_rank == 3
                and _rivals_above(ga, others, env.worst_third_pts, pessimistic=True) <= 7
            )
            statuses[team] = replace(
                st,
                can_advance=st.can_top2 or can_via_third,
                secured_advance=secured,
            )
        out[letter] = replace(ga, statuses=statuses)
    return out
