"""Knockout bracket data: loaders + slot resolution (Phase 5.2).

The official FIFA World Cup 26 bracket is hand-entered ONCE in
data/manual/bracket_2026.yaml (R32 slot pairings, match numbers, dates,
venues) and data/manual/third_place_allocation.csv (FIFA Annex C: which
group's third fills which R32 slot, for each of the 495 possible
combinations of eight qualified thirds). Both files are in git; sources and
verification are recorded in docs/DATA.md. D009 explains why the group
fixtures live in fixtures.parquet but the knockout slots do not.

Loading validates the structure exhaustively — a typo in a slot label must
fail here, not corrupt a simulation. Everything downstream of the loaders is
pure (no I/O).
"""

import csv
import datetime as dt
import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from wc26.config import REPO_ROOT

BRACKET_PATH = REPO_ROOT / "data" / "manual" / "bracket_2026.yaml"
ALLOCATION_PATH = REPO_ROOT / "data" / "manual" / "third_place_allocation.csv"

GROUPS = tuple("ABCDEFGHIJKL")
# The eight group winners whose R32 match takes a third-placed team (FIFA
# regulations art. 12.6; column order of Annex C).
THIRD_SLOT_WINNERS = tuple("ABDEGIKL")

# Host federations: the only teams that ever get home advantage (CLAUDE.md).
HOST_COUNTRY = {
    "united_states": "United States",
    "mexico": "Mexico",
    "canada": "Canada",
}

Round = Literal["r32", "r16", "qf", "sf", "third_place", "final"]
ROUND_ORDER: tuple[Round, ...] = ("r32", "r16", "qf", "sf", "third_place", "final")


@dataclass(frozen=True)
class Slot:
    """One side of a knockout match, before teams are known.

    kind: 'group' (rank 1/2 of a group), 'third' (allocated third-placed
    team, allowed groups listed), 'winner'/'loser' (of an earlier match).
    """

    kind: Literal["group", "third", "winner", "loser"]
    group: str | None = None
    rank: int | None = None
    ref_match: int | None = None
    allowed: tuple[str, ...] | None = None

    @property
    def label(self) -> str:
        if self.kind == "group":
            return f"{self.rank}{self.group}"
        if self.kind == "third":
            return "3rd of " + "/".join(self.allowed or ())
        return f"{'W' if self.kind == 'winner' else 'L'}{self.ref_match}"


@dataclass(frozen=True)
class KnockoutMatch:
    match_no: int
    round: Round
    date: dt.date
    city: str
    country: str
    team_a: Slot
    team_b: Slot


@dataclass(frozen=True)
class Bracket:
    matches: tuple[KnockoutMatch, ...]  # sorted by match_no, 73..104

    def __getitem__(self, match_no: int) -> KnockoutMatch:
        return self.matches[match_no - 73]


class BracketError(ValueError):
    pass


def _parse_slot(raw: object, entry: Mapping[str, object]) -> Slot:
    if raw is None and "third_of" in entry:
        raw_allowed = entry["third_of"]
        if not isinstance(raw_allowed, list) or not raw_allowed:
            raise BracketError(f"bad third_of groups in {entry}")
        allowed = tuple(str(g) for g in raw_allowed)
        if any(g not in GROUPS for g in allowed):
            raise BracketError(f"bad third_of groups in {entry}")
        return Slot(kind="third", allowed=allowed)
    text = str(raw)
    if text[0] in "12" and len(text) == 2 and text[1] in GROUPS:
        return Slot(kind="group", group=text[1], rank=int(text[0]))
    if text[0] in "WL" and text[1:].isdigit():
        return Slot(kind="winner" if text[0] == "W" else "loser", ref_match=int(text[1:]))
    raise BracketError(f"unparseable slot {text!r} in {entry}")


def load_bracket(path: Path = BRACKET_PATH) -> Bracket:
    """Load and exhaustively validate the hand-entered knockout bracket."""
    with path.open() as f:
        raw = yaml.safe_load(f)
    matches: list[KnockoutMatch] = []
    for rnd in ROUND_ORDER:
        for entry in raw["rounds"][rnd]:
            team_a = _parse_slot(entry.get("team_a"), entry)
            team_b = _parse_slot(entry.get("team_b"), entry)
            date = entry["date"]
            if not isinstance(date, dt.date):
                raise BracketError(f"match {entry.get('match')}: date must be a YAML date")
            matches.append(
                KnockoutMatch(
                    match_no=int(entry["match"]),
                    round=rnd,
                    date=date,
                    city=str(entry["city"]),
                    country=str(entry["country"]),
                    team_a=team_a,
                    team_b=team_b,
                )
            )
    matches.sort(key=lambda m: m.match_no)
    _validate_bracket(matches)
    return Bracket(matches=tuple(matches))


def _validate_bracket(matches: list[KnockoutMatch]) -> None:
    if [m.match_no for m in matches] != list(range(73, 105)):
        raise BracketError("bracket must contain exactly matches 73..104")
    by_no = {m.match_no: m for m in matches}

    winners = sorted(
        s.group or ""
        for m in matches
        for s in (m.team_a, m.team_b)
        if s.kind == "group" and s.rank == 1
    )
    runners = sorted(
        s.group or ""
        for m in matches
        for s in (m.team_a, m.team_b)
        if s.kind == "group" and s.rank == 2
    )
    if winners != sorted(GROUPS) or runners != sorted(GROUPS):
        raise BracketError("each group winner and runner-up must appear exactly once in the R32")

    third_slots = {
        m.team_a.group or "": m
        for m in matches
        if m.team_b.kind == "third" and m.team_a.kind == "group"
    }
    if sorted(third_slots) != sorted(THIRD_SLOT_WINNERS):
        raise BracketError(f"third-placed slots must face winners of {THIRD_SLOT_WINNERS}")
    for winner_group, m in third_slots.items():
        if m.team_b.allowed and winner_group in m.team_b.allowed:
            raise BracketError(f"match {m.match_no}: third slot allows the group of its own winner")

    for m in matches:
        for slot in (m.team_a, m.team_b):
            if slot.kind in ("winner", "loser"):
                ref = by_no.get(slot.ref_match or 0)
                if ref is None or ref.match_no >= m.match_no:
                    raise BracketError(f"match {m.match_no}: bad reference {slot.label}")
                if slot.kind == "loser" and ref.round != "sf":
                    raise BracketError("only semi-final losers feed a later match")
    # Every knockout winner except the final's must be consumed exactly once.
    consumed = [
        int(s.ref_match or 0) for m in matches for s in (m.team_a, m.team_b) if s.kind == "winner"
    ]
    if sorted(consumed) != list(range(73, 103)) or len(set(consumed)) != len(consumed):
        raise BracketError("each match winner (73..102) must feed exactly one later match")


def load_allocation(
    bracket: Bracket, path: Path = ALLOCATION_PATH
) -> dict[frozenset[str], dict[str, str]]:
    """FIFA Annex C: {qualified-thirds set -> {winner group -> third's group}}.

    Validates all 495 rows: full C(12,8) coverage, assignments are a
    permutation of the qualified set, and every assignment respects the
    bracket's allowed-groups list for that slot.
    """
    allowed_by_winner = {
        m.team_a.group or "": set(m.team_b.allowed or ())
        for m in bracket.matches
        if m.team_b.kind == "third"
    }
    table: dict[frozenset[str], dict[str, str]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            qualified = frozenset(row["qualified_thirds"])
            assignment = {w: row[f"slot_1{w}"] for w in THIRD_SLOT_WINNERS}
            if len(qualified) != 8 or set(assignment.values()) != set(qualified):
                raise BracketError(f"allocation row {row['option']}: not a permutation of the set")
            for winner, third in assignment.items():
                if third not in allowed_by_winner[winner]:
                    raise BracketError(
                        f"allocation row {row['option']}: 3{third} not allowed vs 1{winner}"
                    )
            if qualified in table:
                raise BracketError(f"duplicate combination {sorted(qualified)}")
            table[qualified] = assignment
    expected = {frozenset(c) for c in itertools.combinations(GROUPS, 8)}
    if set(table) != expected:
        raise BracketError(f"allocation table has {len(table)} combinations, want all 495")
    return table
