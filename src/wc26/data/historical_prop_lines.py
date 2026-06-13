"""Ingest the user's hand-collected Euro 2024 + WC 2022 closing odds into
data/manual/historical_prop_lines.csv (backlog #3, D036).

The user pulled every Euro 2024 (51) and WC 2022 (64) match off OddsPortal —
1X2 plus the FULL match Over/Under ladder (0.5 .. 5.5) — into a free-form RTF.
Team *totals* were not on the site, so this is the STEP-0 fallback path #3
anticipated: MATCH O/U is the new asset (the project had none); the 1X2 is
NOT stored here — it is already in market_odds.parquet in canonical form
(D015) and is used from there for anchoring. The user's own 1X2 cross-checks
that source at mean 0.008 per-outcome (see D036), confirming these are
near-closing consensus prices, not arbitrary quotes.

Source of record: data/manual/sources/eur24wc22_odds.txt (macOS `textutil`
conversion of the user's .rtf, kept alongside for provenance). This module
parses that text, applies the small documented correction set below, backfills
each match's canonical home/away ids + date from market_odds.parquet (a pair
is unique within one tournament, so the join is exact), and writes one
match_total row per O/U line. It is SELF-CHECKING: it must recover exactly
51 + 64 matches and every one must join, else it raises — the source is an
immutable artifact, so any drift is a bug, not noise.

Corrections (auditable patch; the raw source is left untouched):
- Spelling that blocks team resolution:
    "SUA" -> United States;  "Saudia Arabia" -> Saudi Arabia (x3);
    "South Korea Portugal" -> split (the only matchup with no separator).
- Decimal typos caught by de-vig + monotonicity (over/under sanity):
    Argentina v Australia  O5.5 over 1.400 -> 14.00
    Brazil v South Korea   O5.5 over 1.200 -> 12.00
  (Poland v Netherlands' 1X2 draw 44.0 -> 4.40 is a 1X2 typo only; 1X2 is
   not stored here, so it is corrected in the source-cross-check, not below.)
- Malformed lines dropped (a tail line, never used for pricing):
    Slovakia v Romania  O5.5 (over 15.5 < its own O4.5 17.0 — one is mistyped)
    France v Australia  O0.5 (under odds missing in the source)
"""

import re
from typing import Any

import pandas as pd
import pandera.pandas as pa

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

SOURCE_TXT = REPO_ROOT / "data" / "manual" / "sources" / "eur24wc22_odds.txt"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
HISTORICAL_PROP_LINES_CSV = REPO_ROOT / "data" / "manual" / "historical_prop_lines.csv"

SOURCE_URLS = {
    "UEFA Euro": "https://www.oddsportal.com/football/europe/euro-2024/results/",
    "FIFA World Cup": "https://www.oddsportal.com/football/world/world-cup-2022/results/",
}

# --- documented corrections (see module docstring) ---
_NAME_FIX = {"sua": "United States", "saudia arabia": "Saudi Arabia"}
_SPLIT_FIX = {"South Korea Portugal": ["South Korea", "Portugal"]}
_OU_FIX = {  # (raw matchup, line) -> (over, under)
    ("Argentina v Australia", 5.5): (14.00, 1.05),
    ("Brazil v South Korea", 5.5): (12.00, 1.07),
}
_OU_DROP = {("Slovakia v Romania", 5.5), ("France v Australia", 0.5)}

_LADDER = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
_EXPECTED = {"UEFA Euro": 51, "FIFA World Cup": 64}

HISTORICAL_PROP_LINES_SCHEMA = pa.DataFrameSchema(
    {
        "tournament": pa.Column(str, pa.Check.isin(list(_EXPECTED))),
        "date": pa.Column(pa.DateTime),
        "home_team": pa.Column(str),  # canonical id (D008 invariant)
        "away_team": pa.Column(str),  # canonical id
        "market": pa.Column(str, pa.Check.eq("match_total")),
        "line": pa.Column(float, pa.Check.isin(list(_LADDER))),
        "over_odds": pa.Column(float, pa.Check.gt(1.0)),
        "under_odds": pa.Column(float, pa.Check.gt(1.0)),
        "book": pa.Column(str),
        "is_closing": pa.Column(bool),
        "source_url": pa.Column(str),
    },
    strict="filter",
    coerce=True,
)


def _fix_name(n: str) -> str:
    return _NAME_FIX.get(n.strip().lower(), n.strip())


def _split_teams(name: str) -> list[str]:
    if name in _SPLIT_FIX:
        return _SPLIT_FIX[name]
    for sep in (" vs ", " v ", " - "):
        if sep in name:
            return [p.strip() for p in name.split(sep, 1)]
    return [name]


_STAGE_RANK = {"group": 0, "knockout": 1}


def parse_source(text: str) -> list[dict[str, Any]]:
    """Parse the OddsPortal text dump into one dict per match.

    Each dict: tournament, stage (group/knockout), raw matchup, [team0, team1],
    and totals {line: (over, under)}. 1X2 is parsed past but not retained
    (D036). Stage + file order disambiguate a rematched pair (WC22 Croatia v
    Morocco met in Group F AND the 3rd-place playoff).
    """
    matches: list[dict[str, Any]] = []
    tournament: str | None = None
    stage = "group"
    cur: dict[str, Any] | None = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if low == "eur24":
            tournament = "UEFA Euro"
            continue
        if low.startswith("worldcup"):
            tournament = "FIFA World Cup"
            continue
        if low == "euro24 and wc22":
            continue
        if "group stage" in low:
            stage = "group"
            continue
        if "playoff" in low:
            stage = "knockout"
            continue
        if low.startswith("1/x/2"):
            continue  # 1X2 not stored here
        if low.startswith("total"):  # "Total O/U" or "Total Over/Under"
            m = re.search(r"\+?\s*([0-9]\.5)\s*-?\s*([0-9]+\.?[0-9]*)\s*/\s*([0-9]+\.?[0-9]*)", s)
            if cur is not None and m:
                cur["totals"][float(m.group(1))] = (float(m.group(2)), float(m.group(3)))
            continue
        # otherwise: a match header
        if cur is not None:
            matches.append(cur)
        name = s.rstrip(":").strip()
        cur = {
            "tournament": tournament,
            "stage": stage,
            "raw": name,
            "teams": [_fix_name(p) for p in _split_teams(name)],
            "totals": {},
        }
    if cur is not None:
        matches.append(cur)
    return matches


def build_historical_prop_lines(write: bool = True) -> pd.DataFrame:
    """Parse the source, apply corrections, backfill ids+dates, write the CSV."""
    reg = registry()
    matches = parse_source(SOURCE_TXT.read_text())

    counts = {t: sum(m["tournament"] == t for m in matches) for t in _EXPECTED}
    if counts != _EXPECTED:
        raise ValueError(f"source parse recovered {counts}, expected {_EXPECTED} — source drift")

    # market_odds gives the canonical (home_id, away_id, date) per match. Key by
    # (tournament, pair): a pair can recur ACROSS tournaments (France v Poland —
    # WC22 R16 and Euro24 Group D) and WITHIN one via a 3rd-place rematch of a
    # group pair (WC22 Croatia v Morocco). Within a (tournament, pair) bucket,
    # zip source-by-stage to market_odds-by-date.
    mo = pd.read_parquet(PROCESSED_DIR / "market_odds.parquet")
    mo["year"] = mo["date"].dt.year
    mo = mo[
        ((mo.tournament == "UEFA Euro") & (mo.year == 2024))
        | ((mo.tournament == "FIFA World Cup") & (mo.year == 2022))
    ]
    mo_by_key: dict[tuple[str, frozenset[str]], list[Any]] = {}
    for r in mo.itertuples(index=False):
        pair = frozenset((str(r.home_id), str(r.away_id)))
        mo_by_key.setdefault((str(r.tournament), pair), []).append(r)
    for hits in mo_by_key.values():
        hits.sort(key=lambda r: r.date)

    src_by_key: dict[tuple[str, frozenset[str]], list[dict[str, Any]]] = {}
    for m in matches:
        if len(m["teams"]) != 2:
            raise ValueError(f"could not split matchup {m['raw']!r} into two teams")
        ids = frozenset(reg.resolve_lenient(t) for t in m["teams"])
        src_by_key.setdefault((m["tournament"], ids), []).append(m)

    for key, src_list in src_by_key.items():
        mo_hits = mo_by_key.get(key)
        if not mo_hits or len(mo_hits) != len(src_list):
            raise ValueError(
                f"{key}: {len(src_list)} source matches vs "
                f"{len(mo_hits) if mo_hits else 0} market_odds rows — fix alias/rematch"
            )
        ordered = sorted(src_list, key=lambda x: _STAGE_RANK[x["stage"]])
        for m, hit in zip(ordered, mo_hits, strict=True):
            m["date"] = pd.Timestamp(hit.date).date().isoformat()
            m["home_id"], m["away_id"] = hit.home_id, hit.away_id

    rows: list[dict[str, Any]] = []
    for m in matches:
        for line, (over, under) in sorted(m["totals"].items()):
            ou_key = (m["raw"], line)
            if ou_key in _OU_DROP:
                continue
            if ou_key in _OU_FIX:
                over, under = _OU_FIX[ou_key]
            rows.append(
                {
                    "tournament": m["tournament"],
                    "date": m["date"],
                    "home_team": m["home_id"],
                    "away_team": m["away_id"],
                    "market": "match_total",
                    "line": line,
                    "over_odds": over,
                    "under_odds": under,
                    "book": "oddsportal_avg",
                    "is_closing": True,
                    "source_url": SOURCE_URLS[m["tournament"]],
                }
            )

    df = pd.DataFrame(rows)
    n_matches = len(df[["tournament", "date", "home_team", "away_team"]].drop_duplicates())
    if n_matches != sum(_EXPECTED.values()):
        raise ValueError(
            f"{n_matches} distinct matches in output, expected {sum(_EXPECTED.values())}"
        )
    df = HISTORICAL_PROP_LINES_SCHEMA.validate(df)
    if write:
        df.to_csv(HISTORICAL_PROP_LINES_CSV, index=False)
    return df


def load_historical_prop_lines() -> pd.DataFrame:
    """Read + validate data/manual/historical_prop_lines.csv."""
    df = pd.read_csv(HISTORICAL_PROP_LINES_CSV, parse_dates=["date"])
    return HISTORICAL_PROP_LINES_SCHEMA.validate(df)
