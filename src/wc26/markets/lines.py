"""Parse and validate data/manual/lines.csv (manually entered book lines, D007).

File format (one row per quoted side; both sides of a market must be present
so it can be de-vigged):

    ts_utc,match,market,line,side,odds,book
    2026-06-12T15:00:00,USA v Paraguay,team_total:Paraguay,1.5,over,-110,bet365
    2026-06-12T15:00:00,USA v Paraguay,team_total:Paraguay,1.5,under,-110,bet365

- ts_utc: when the line was read off the book (ISO 8601, UTC, no tz suffix)
- match:  "<home> v <away>" — any registry alias, strict resolution
- market: "team_total:<team>" — the team whose goals the O/U is on
- line:   half-integer (x.5); whole-number (push) lines are not priced
- odds:   decimal ("1.91") or signed American ("-110"); stored decimal-only
- book:   free text, part of the market key (same line at two books = two rows
  per side)

HARD GUARDS (all raise LineError; tests pin them):
- only gate-cleared markets are accepted — today that is team totals ONLY;
  match totals (D019) and corners/cards (D021) are quarantined
- the match must resolve to exactly one not-yet-played WC26 fixture (a line
  for an unknown or finished match can't be priced)
- stale quotes (older than MAX_AGE) are refused, not silently skipped: a
  stale lines.csv means the file wasn't refreshed today — delete old rows
- unknown team names raise UnknownTeamError (never fuzzy-matched)
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from wc26.config import REPO_ROOT
from wc26.data.teams import registry
from wc26.markets.odds import parse_odds

LINES_PATH = REPO_ROOT / "data" / "manual" / "lines.csv"
MAX_AGE = pd.Timedelta(hours=24)

# The only market families wc26 edges may price. Extending this set requires
# green gates in docs/MODEL.md plus a DECISIONS.md entry (see D019/D021).
PRICEABLE_MARKETS = frozenset({"team_total"})
QUARANTINED_MARKETS = {
    "match_total": "D019 — match-totals signal failed its calibration gate (O2.5 slope 0.13)",
    "corners": "D021 — corners model lost to the naive baseline; reference only",
    "cards": "D021 — cards model lost to the naive baseline; reference only",
}


class LineError(ValueError):
    pass


@dataclass(frozen=True)
class TwoWayLine:
    """One de-viggable book market: both sides of a team-total O/U quote."""

    ts: pd.Timestamp  # newer of the two sides' timestamps
    match_date: pd.Timestamp
    home_id: str
    away_id: str
    neutral: bool
    team_id: str  # whose goals the line is on
    market: str  # canonical, e.g. "team_total:paraguay"
    line: float
    over_odds: float
    under_odds: float
    book: str

    @property
    def match(self) -> str:
        return f"{self.home_id} v {self.away_id}"


def _parse_market(market: str, home_id: str, away_id: str) -> tuple[str, str]:
    """-> (family, team_id). Enforces the gate-clearance guard."""
    family, _, qualifier = market.partition(":")
    family = family.strip().lower()
    if family in QUARANTINED_MARKETS:
        raise LineError(
            f"market {family!r} is QUARANTINED and must not be priced "
            f"({QUARANTINED_MARKETS[family]}; see DECISIONS.md)"
        )
    if family not in PRICEABLE_MARKETS:
        raise LineError(
            f"unknown market {market!r} — gate-cleared markets: {sorted(PRICEABLE_MARKETS)}"
        )
    if not qualifier.strip():
        raise LineError(f"market {market!r} needs a team, e.g. 'team_total:Paraguay'")
    team_id = registry().resolve(qualifier.strip())
    if team_id not in (home_id, away_id):
        raise LineError(f"team_total team {team_id!r} is not in match {home_id} v {away_id}")
    return family, team_id


def resolve_fixture(
    a_id: str, b_id: str, fixtures: pd.DataFrame
) -> tuple[pd.Timestamp, str, str, bool]:
    """Two canonical ids -> (date, home_id, away_id, neutral) of their unique
    unplayed WC26 fixture (orientation as stored in the fixtures table).

    Shared by the line parser and the anchor parser (markets/anchors.py) so
    both apply the identical 'must be one not-yet-played fixture' guard.
    """
    hit = fixtures[
        ((fixtures["home_id"] == a_id) & (fixtures["away_id"] == b_id))
        | ((fixtures["home_id"] == b_id) & (fixtures["away_id"] == a_id))
    ]
    if hit.empty:
        raise LineError(f"no WC26 fixture for {a_id} v {b_id} — no model prediction exists for it")
    if len(hit) > 1:
        raise LineError(f"ambiguous fixture for {a_id} v {b_id} ({len(hit)} rows)")
    row = hit.iloc[0]
    if bool(row["played"]):
        raise LineError(f"{a_id} v {b_id} is already played — refusing to price a finished match")
    return pd.Timestamp(row["date"]), str(row["home_id"]), str(row["away_id"]), bool(row["neutral"])


def _resolve_match(match: str, fixtures: pd.DataFrame) -> tuple[pd.Timestamp, str, str, bool]:
    """'A v B' -> (date, home_id, away_id, neutral) of its unique unplayed fixture."""
    parts = [p.strip() for p in match.split(" v ")]
    if len(parts) != 2 or not all(parts):
        raise LineError(f"match must be '<home> v <away>', got {match!r}")
    a, b = (registry().resolve(p) for p in parts)
    return resolve_fixture(a, b, fixtures)


def load_lines(
    fixtures: pd.DataFrame,
    path: Path = LINES_PATH,
    now: pd.Timestamp | None = None,
) -> list[TwoWayLine]:
    """Parse lines.csv into validated, de-viggable two-way markets."""
    now = now if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    expected = ["ts_utc", "match", "market", "line", "side", "odds", "book"]
    if list(df.columns) != expected:
        raise LineError(f"{path} columns must be {expected}, got {list(df.columns)}")
    if df.empty:
        return []

    sides: dict[tuple[str, str, str, float, str], dict[str, tuple[pd.Timestamp, float]]] = {}
    meta: dict[tuple[str, str, str, float, str], TwoWayLine] = {}
    for i, row in enumerate(df.itertuples(index=False), start=2):
        where = f"{path.name} row {i}"
        ts = pd.Timestamp(str(row.ts_utc))
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        age = now - ts
        if age > MAX_AGE:
            raise LineError(
                f"{where}: quote is stale ({age.components.days}d "
                f"{age.components.hours}h old) — re-enter today's lines and delete old rows"
            )
        match_date, home_id, away_id, neutral = _resolve_match(str(row.match), fixtures)
        family, team_id = _parse_market(str(row.market), home_id, away_id)
        line = float(str(row.line))
        if (2 * line) % 2 != 1:
            raise LineError(f"{where}: line must be a half-integer (x.5), got {row.line}")
        side = str(row.side).strip().lower()
        if side not in ("over", "under"):
            raise LineError(f"{where}: side must be 'over' or 'under', got {row.side!r}")
        odds = parse_odds(str(row.odds))
        book = str(row.book).strip()

        key = (home_id, away_id, team_id, line, book)
        quoted = sides.setdefault(key, {})
        if side in quoted:
            raise LineError(f"{where}: duplicate {side} quote for {key}")
        quoted[side] = (ts, odds)
        meta[key] = TwoWayLine(
            ts=ts,
            match_date=match_date,
            home_id=home_id,
            away_id=away_id,
            neutral=neutral,
            team_id=team_id,
            market=f"{family}:{team_id}",
            line=line,
            over_odds=0.0,
            under_odds=0.0,
            book=book,
        )

    out: list[TwoWayLine] = []
    for key, quoted in sides.items():
        missing = {"over", "under"} - quoted.keys()
        if missing:
            raise LineError(
                f"market {key} is missing its {missing.pop()} quote — both sides are "
                f"required to de-vig (D005)"
            )
        base = meta[key]
        out.append(
            TwoWayLine(
                ts=max(quoted["over"][0], quoted["under"][0]),
                match_date=base.match_date,
                home_id=base.home_id,
                away_id=base.away_id,
                neutral=base.neutral,
                team_id=base.team_id,
                market=base.market,
                line=base.line,
                over_odds=quoted["over"][1],
                under_odds=quoted["under"][1],
                book=base.book,
            )
        )
    return out
