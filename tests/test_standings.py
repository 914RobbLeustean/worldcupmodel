"""Tiebreaker + qualification-analysis unit tests on constructed fixtures.

The tiebreakers are FIFA WC2026 Regulations art. 13 (D023). The decisive
difference vs the 2018/2022 procedure — head-to-head BEFORE overall goal
difference — is pinned explicitly in test_h2h_beats_overall_gd.
"""

from wc26.sim.standings import (
    GroupMatch,
    Record,
    analyse_group,
    rank_group,
    rank_thirds,
    records,
    resolve_cross_group,
)

TEAMS = ["t1", "t2", "t3", "t4"]
LOTS = ["t1", "t2", "t3", "t4"]
NO_CONDUCT: dict[str, float] = {}
NO_ELO: dict[str, float] = {}


def m(h: str, a: str, hg: int, ag: int) -> GroupMatch:
    return GroupMatch(h, a, hg, ag)


def test_records_basic() -> None:
    rec = records([m("t1", "t2", 2, 0), m("t1", "t3", 1, 1)], TEAMS)
    assert rec["t1"] == Record(points=4, gd=2, gf=3)
    assert rec["t2"] == Record(points=0, gd=-2, gf=0)
    assert rec["t3"] == Record(points=1, gd=0, gf=1)
    assert rec["t4"] == Record(points=0, gd=0, gf=0)


def test_points_order_no_ties() -> None:
    matches = [
        m("t1", "t2", 1, 0),
        m("t1", "t3", 2, 0),
        m("t1", "t4", 3, 0),
        m("t2", "t3", 1, 0),
        m("t2", "t4", 2, 0),
        m("t3", "t4", 1, 0),
    ]
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, LOTS) == ["t1", "t2", "t3", "t4"]


def test_h2h_beats_overall_gd() -> None:
    """2026 art. 13 step 1: h2h FIRST — the 2018/2022 order would invert this.

    t1 and t2 finish level on 6 points. t2's overall GD is far better, but t1
    won the head-to-head, so t1 ranks above t2 under the 2026 rules.
    """
    matches = [
        m("t1", "t2", 1, 0),  # h2h: t1 over t2
        m("t1", "t3", 1, 0),
        m("t1", "t4", 0, 1),  # t1: 6 pts, overall gd +1
        m("t2", "t3", 5, 0),
        m("t2", "t4", 5, 0),  # t2: 6 pts, overall gd +9
        m("t3", "t4", 0, 0),
    ]
    rec = records(matches, TEAMS)
    assert rec["t1"].points == rec["t2"].points == 6
    assert rec["t2"].gd > rec["t1"].gd
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, LOTS)[:2] == ["t1", "t2"]


def test_h2h_draw_falls_to_overall_gd() -> None:
    matches = [
        m("t1", "t2", 1, 1),  # h2h level
        m("t1", "t3", 2, 0),
        m("t1", "t4", 1, 0),  # t1: 7 pts, gd +4... see below
        m("t2", "t3", 4, 0),
        m("t2", "t4", 1, 0),  # t2: 7 pts, gd +6
        m("t3", "t4", 0, 0),
    ]
    rec = records(matches, TEAMS)
    assert rec["t1"].points == rec["t2"].points == 7
    assert rec["t2"].gd > rec["t1"].gd
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, LOTS)[:2] == ["t2", "t1"]


def test_three_way_tie_h2h_minileague_then_reapply() -> None:
    """t1/t2/t3 all on 6 points (cycle); the mini-league separates t1, then
    a-c re-apply to the remaining pair (step 2, first sentence)."""
    matches = [
        m("t1", "t2", 3, 0),
        m("t2", "t3", 2, 1),
        m("t3", "t1", 1, 0),  # cycle; mini-league gd: t1 +2, t2 -2, t3 0
        m("t1", "t4", 1, 0),
        m("t2", "t4", 1, 0),
        m("t3", "t4", 1, 0),
    ]
    # mini-league: all 3 pts; gd t1 +2, t3 0, t2 -2 -> t1, t3, t2
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, LOTS) == ["t1", "t3", "t2", "t4"]


def test_three_way_pure_cycle_falls_to_overall() -> None:
    """1-0 cycle: the mini-league is fully level, so step 2 d-f (overall GD,
    then GF) decides — margins vs t4 differ."""
    matches = [
        m("t1", "t2", 1, 0),
        m("t2", "t3", 1, 0),
        m("t3", "t1", 1, 0),
        m("t1", "t4", 4, 0),  # overall gd +4
        m("t2", "t4", 2, 0),  # +2
        m("t3", "t4", 3, 0),  # +3
    ]
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, LOTS) == ["t1", "t3", "t2", "t4"]


def test_conduct_then_elo_then_lots() -> None:
    """Fully symmetric group: conduct, then the Elo proxy, then lots_order."""
    matches = [
        m("t1", "t2", 0, 0),
        m("t1", "t3", 0, 0),
        m("t1", "t4", 0, 0),
        m("t2", "t3", 0, 0),
        m("t2", "t4", 0, 0),
        m("t3", "t4", 0, 0),
    ]
    conduct = {"t3": -1.0}  # one yellow card for t3
    order = rank_group(matches, TEAMS, conduct, NO_ELO, LOTS)
    assert order[3] == "t3"  # worst conduct ranks last
    elo = {"t1": 1500.0, "t2": 1600.0, "t3": 1400.0, "t4": 1700.0}
    assert rank_group(matches, TEAMS, NO_CONDUCT, elo, LOTS) == ["t4", "t2", "t1", "t3"]
    # everything identical -> lots_order wins
    assert rank_group(matches, TEAMS, NO_CONDUCT, NO_ELO, ["t4", "t3", "t2", "t1"]) == [
        "t4",
        "t3",
        "t2",
        "t1",
    ]


def test_rank_thirds_order() -> None:
    recs = {
        "a3": Record(points=4, gd=0, gf=2),
        "b3": Record(points=4, gd=1, gf=1),
        "c3": Record(points=3, gd=5, gf=9),
        "d3": Record(points=4, gd=0, gf=3),
    }
    lots = ["a3", "b3", "c3", "d3"]
    assert rank_thirds(recs, NO_CONDUCT, NO_ELO, lots) == ["b3", "d3", "a3", "c3"]


# --- qualification analysis -------------------------------------------------


def _complete_group(prefix: str, third_points: int) -> tuple[list[GroupMatch], list[str]]:
    """A finished group whose 3rd-placed team ends on `third_points` (3 or 4)."""
    a, b, c, d = (f"{prefix}{i}" for i in range(1, 5))
    if third_points == 4:
        # a 7, b 5, c 4, d 0
        matches = [
            m(a, b, 1, 1),
            m(a, c, 2, 0),
            m(a, d, 2, 0),
            m(b, c, 1, 1),
            m(b, d, 1, 0),
            m(c, d, 3, 0),
        ]
    elif third_points == 3:
        # a 9, b 6, c 3, d 0
        matches = [
            m(a, b, 2, 0),
            m(a, c, 2, 0),
            m(a, d, 2, 0),
            m(b, c, 2, 0),
            m(b, d, 2, 0),
            m(c, d, 2, 0),
        ]
    else:
        raise ValueError(third_points)
    return matches, [a, b, c, d]


def test_analysis_complete_group_collapses() -> None:
    matches, teams = _complete_group("x", 3)
    ga = analyse_group("X", matches, teams, [], NO_CONDUCT, NO_ELO, teams)
    assert ga.order_now == teams
    assert ga.statuses["x1"].secured_top2 and ga.statuses["x2"].secured_top2
    assert not ga.statuses["x3"].can_top2 and not ga.statuses["x4"].can_top2
    assert ga.min_third_points == ga.max_third_points == 3


def test_eliminated_and_secured_cross_group() -> None:
    """12 complete groups; thirds elsewhere all on 4 pts; group L's third has
    3 pts -> 4th is out everywhere, 3rd is out of the best-8 race, top2 are
    through."""
    analyses = {}
    for letter in "ABCDEFGHIJK":
        matches, teams = _complete_group(letter.lower(), 4)
        analyses[letter] = analyse_group(letter, matches, teams, [], NO_CONDUCT, NO_ELO, teams)
    matches, teams = _complete_group("l", 3)
    analyses["L"] = analyse_group("L", matches, teams, [], NO_CONDUCT, NO_ELO, teams)

    resolved = resolve_cross_group(analyses)
    # group A's third (4 pts): ties vs the other 4-pt thirds CAN fall its way
    assert resolved["A"].statuses["a3"].can_advance
    # ...but is not secured: 11 rivals can rank above it on free margins.
    assert not resolved["A"].statuses["a3"].secured_advance
    # group L's third (3 pts): 11 other thirds are locked on 4 -> eliminated
    assert resolved["L"].statuses["l3"].eliminated
    assert resolved["L"].statuses["l4"].eliminated
    assert resolved["L"].statuses["l1"].secured_advance
    assert resolved["L"].statuses["l2"].secured_advance


def test_partial_group_envelope() -> None:
    """After MD2: a/b on 6, c/d on 0 -> c/d cannot reach top2, a/b secured
    top2; the MD3 games are a-b and c-d."""
    a, b, c, d = "p1", "p2", "p3", "p4"
    played = [m(a, c, 2, 0), m(b, d, 2, 0), m(a, d, 2, 0), m(b, c, 2, 0)]
    remaining = [(a, b), (c, d)]
    ga = analyse_group("P", played, [a, b, c, d], remaining, NO_CONDUCT, NO_ELO, [a, b, c, d])
    assert ga.statuses[a].secured_top2 and ga.statuses[b].secured_top2
    assert not ga.statuses[c].can_top2 and not ga.statuses[d].can_top2
    # the third is the better of c/d: a c-d draw leaves it on 1 point, a
    # decisive result on 3
    assert ga.min_third_points == 1
    assert ga.max_third_points == 3
