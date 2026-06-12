"""Bracket + third-place allocation loaders (Phase 5.2).

The hand-entered files are validated structurally on load; here we addition-
ally pin spot rows against the FIFA regulations PDF (May 2025, art. 12.6 and
Annex C options 1/495 — read independently from the source document, see
docs/DATA.md).
"""

import datetime as dt

import pytest

from wc26.sim.bracket import (
    BracketError,
    load_allocation,
    load_bracket,
)

BRACKET = load_bracket()
ALLOCATION = load_allocation(BRACKET)


def test_bracket_structure_loads_and_validates() -> None:
    assert len(BRACKET.matches) == 32
    assert [m.match_no for m in BRACKET.matches] == list(range(73, 105))


def test_r32_pairings_match_fifa_regulations() -> None:
    """Art. 12.6 spot checks."""
    m73 = BRACKET[73]
    assert (m73.team_a.label, m73.team_b.label) == ("2A", "2B")
    m74 = BRACKET[74]
    assert m74.team_a.label == "1E"
    assert m74.team_b.allowed == ("A", "B", "C", "D", "F")
    m79 = BRACKET[79]
    assert m79.team_a.label == "1A"
    assert m79.team_b.allowed == ("C", "E", "F", "H", "I")
    assert m79.country == "Mexico"  # Estadio Azteca — host home advantage
    m88 = BRACKET[88]
    assert (m88.team_a.label, m88.team_b.label) == ("2D", "2G")
    assert BRACKET[104].date == dt.date(2026, 7, 19)
    assert BRACKET[104].city == "East Rutherford"


def test_r16_to_final_progression_matches_fifa() -> None:
    """Art. 12.7-12.11: the bracket graph, by winner references."""
    refs = {
        89: (74, 77),
        90: (73, 75),
        91: (76, 78),
        92: (79, 80),
        93: (83, 84),
        94: (81, 82),
        95: (86, 88),
        96: (85, 87),
        97: (89, 90),
        98: (93, 94),
        99: (91, 92),
        100: (95, 96),
        101: (97, 98),
        102: (99, 100),
        104: (101, 102),
    }
    for match_no, (a, b) in refs.items():
        match = BRACKET[match_no]
        assert (match.team_a.ref_match, match.team_b.ref_match) == (a, b), match_no
    third = BRACKET[103]
    assert third.team_a.kind == "loser" and third.team_b.kind == "loser"
    assert (third.team_a.ref_match, third.team_b.ref_match) == (101, 102)


def test_allocation_covers_all_495_combinations() -> None:
    assert len(ALLOCATION) == 495
    for qualified, assignment in ALLOCATION.items():
        assert set(assignment.values()) == set(qualified)


def test_allocation_option_1_and_495_pin_fifa_annex_c() -> None:
    """Annex C first and last rows, read from the FIFA PDF by hand."""
    option1 = ALLOCATION[frozenset("EFGHIJKL")]
    assert option1 == {
        "A": "E",
        "B": "J",
        "D": "I",
        "E": "F",
        "G": "H",
        "I": "G",
        "K": "L",
        "L": "K",
    }
    option495 = ALLOCATION[frozenset("ABCDEFGH")]
    assert option495 == {
        "A": "H",
        "B": "G",
        "D": "B",
        "E": "C",
        "G": "A",
        "I": "F",
        "K": "D",
        "L": "E",
    }


def test_no_third_meets_its_own_group_winner() -> None:
    """A team can never face its own group's winner in the R32."""
    allowed_by_winner = {
        m.team_a.group: set(m.team_b.allowed or ())
        for m in BRACKET.matches
        if m.team_b.kind == "third"
    }
    for winner_group, allowed in allowed_by_winner.items():
        assert winner_group not in allowed
    for assignment in ALLOCATION.values():
        for winner_group, third_group in assignment.items():
            assert winner_group != third_group


def test_loader_rejects_bad_slot(tmp_path: object) -> None:
    import yaml

    from wc26.sim.bracket import BRACKET_PATH

    raw = yaml.safe_load(BRACKET_PATH.read_text())
    raw["rounds"]["final"][0]["team_a"] = "W999"
    bad = tmp_path / "bad.yaml"  # type: ignore[operator]
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(BracketError):
        load_bracket(bad)
