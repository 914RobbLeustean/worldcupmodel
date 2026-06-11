"""Team registry: 48 teams, 12 groups, alias resolution, strictness."""

import pytest

from wc26.data.teams import TeamRegistry, UnknownTeamError


@pytest.fixture(scope="module")
def reg() -> TeamRegistry:
    return TeamRegistry()


def test_registry_shape(reg: TeamRegistry) -> None:
    assert len(reg.teams) == 48
    for letter in "ABCDEFGHIJKL":
        assert len(reg.group(letter)) == 4, f"group {letter} must have 4 teams"
    hosts = {t.id for t in reg.teams.values() if t.host}
    assert hosts == {"mexico", "canada", "united_states"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("USA", "united_states"),
        ("Korea Republic", "south_korea"),
        ("Türkiye", "turkey"),
        ("Czech Republic", "czechia"),
        ("Côte d'Ivoire", "ivory_coast"),
        ("curaçao", "curacao"),
        ("Congo DR", "dr_congo"),
        ("Cabo Verde", "cape_verde"),
        ("IR Iran", "iran"),
        ("Bosnia-Herzegovina", "bosnia_herzegovina"),
        ("england", "england"),
    ],
)
def test_alias_resolution(reg: TeamRegistry, raw: str, expected: str) -> None:
    assert reg.resolve(raw) == expected


def test_unknown_team_raises_with_hint(reg: TeamRegistry) -> None:
    with pytest.raises(UnknownTeamError, match=r"teams\.yaml"):
        reg.resolve("Atlantis")


def test_lenient_passthrough_for_historical_teams(reg: TeamRegistry) -> None:
    # Full-history Elo universe: known aliases canonicalize, the rest slug.
    assert reg.resolve_lenient("West Germany") == "germany"
    assert reg.resolve_lenient("Czechoslovakia") == "czechoslovakia"
    assert reg.resolve_lenient("Soviet Union") == "soviet_union"
