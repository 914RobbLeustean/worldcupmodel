"""Canonical team registry (config/teams.yaml).

Two resolution modes (see DECISIONS.md D008):
- resolve(): strict — for anything touching WC26 models, markets, or the
  ledger. Unknown name raises UnknownTeamError with a fix-it hint.
- resolve_lenient(): for the full historical results universe (~300 national
  teams) used only to compute Elo. Known aliases map to canonical ids;
  anything else passes through as a normalized slug. Historical teams never
  cross into pricing code, so strictness there buys nothing.
"""

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from wc26.config import REPO_ROOT

TEAMS_PATH = REPO_ROOT / "config" / "teams.yaml"


class UnknownTeamError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"Unknown team name {name!r}. If this is a legitimate new spelling, "
            f"add it to the aliases list in config/teams.yaml."
        )


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    group: str
    host: bool


def _norm(name: str) -> str:
    """Case- and accent-insensitive key for alias lookup."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower().replace("&", "and")


def _slug(name: str) -> str:
    cleaned = _norm(name).replace("'", "").replace("-", " ").replace(".", " ")
    return "_".join(cleaned.split())


class TeamRegistry:
    def __init__(self, path: Path = TEAMS_PATH) -> None:
        with path.open() as f:
            raw = yaml.safe_load(f)
        self.teams: dict[str, Team] = {}
        self._alias_index: dict[str, str] = {}
        for entry in raw["teams"]:
            team = Team(
                id=entry["id"],
                name=entry["name"],
                group=entry["group"],
                host=bool(entry.get("host", False)),
            )
            if team.id in self.teams:
                raise ValueError(f"Duplicate team id in teams.yaml: {team.id}")
            self.teams[team.id] = team
            for alias in [team.id, team.name, *entry.get("aliases", [])]:
                key = _norm(alias)
                existing = self._alias_index.get(key)
                if existing is not None and existing != team.id:
                    raise ValueError(f"Alias {alias!r} maps to both {existing} and {team.id}")
                self._alias_index[key] = team.id

    def resolve(self, name: str) -> str:
        """Strict: name/alias -> canonical id, or UnknownTeamError."""
        team_id = self._alias_index.get(_norm(name))
        if team_id is None:
            raise UnknownTeamError(name)
        return team_id

    def resolve_lenient(self, name: str) -> str:
        """Alias -> canonical id if known, else normalized slug passthrough."""
        return self._alias_index.get(_norm(name), _slug(name))

    def __getitem__(self, team_id: str) -> Team:
        return self.teams[team_id]

    @property
    def wc26_ids(self) -> frozenset[str]:
        return frozenset(self.teams)

    def group(self, letter: str) -> list[Team]:
        return [t for t in self.teams.values() if t.group == letter.upper()]


_registry: TeamRegistry | None = None


def registry() -> TeamRegistry:
    global _registry
    if _registry is None:
        _registry = TeamRegistry()
    return _registry
