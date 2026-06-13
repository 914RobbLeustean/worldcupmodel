"""Parse data/manual/anchors.csv — the book's 1X2 quote per match (D028/D032).

Market-anchored pricing (D028): team totals are priced from the Dixon-Coles
grid solved to reproduce the book's de-vigged 1X2, not from the engine grid
(the engine's 1X2 opinion earned blend weight w*=0.00 vs the market). This
module parses the anchor quotes; the grid solve lives in
models/market_anchor.py and the CLI glues them (markets never compute model
probabilities — architecture rule).

File format (one row per match; the THREE-way 1X2 the book is quoting):

    ts_utc,match,home_odds,draw_odds,away_odds,book
    2026-06-13T17:00:00,USA v Paraguay,2.12,3.30,4.09,superbet

- ts_utc: when the quote was read (ISO 8601, UTC); stale (>24 h) is refused
- match:  "<home> v <away>" — any registry alias; home_odds is the FIRST
  team as typed, regardless of the fixtures table's orientation (a flipped
  entry has its home/away probabilities swapped to fixture orientation here)
- *_odds: decimal or signed American; de-vigged multiplicatively (D005)

Same hard guards as lines.py (one unplayed WC26 fixture, unknown team raises,
staleness). A team-total quote whose match has no anchor here is UNPRICEABLE
(the CLI refuses to flag/log a bet for it) — that is the D028 discipline:
no anchor, no bet.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from penaltyblog.implied import calculate_implied

from wc26.config import REPO_ROOT
from wc26.data.teams import registry
from wc26.markets.lines import MAX_AGE, LineError, resolve_fixture
from wc26.markets.odds import parse_odds

ANCHORS_PATH = REPO_ROOT / "data" / "manual" / "anchors.csv"
_COLUMNS = ["ts_utc", "match", "home_odds", "draw_odds", "away_odds", "book"]


@dataclass(frozen=True)
class MatchAnchor:
    """A book's de-vigged 1X2 for one match, in fixtures-table orientation."""

    ts: pd.Timestamp
    match_date: pd.Timestamp
    home_id: str  # fixtures-table home side
    away_id: str
    neutral: bool
    fair_p_home: float  # P(home_id wins, 90'), de-vigged
    fair_p_draw: float
    fair_p_away: float
    book: str

    @property
    def match(self) -> str:
        return f"{self.home_id} v {self.away_id}"


def devig_1x2(home_odds: float, draw_odds: float, away_odds: float) -> tuple[float, float, float]:
    """(fair home, draw, away) by multiplicative de-vig (D005), via penaltyblog."""
    result = calculate_implied([home_odds, draw_odds, away_odds], method="multiplicative")
    p_home, p_draw, p_away = (float(p) for p in result.probabilities)
    return p_home, p_draw, p_away


def load_anchors(
    fixtures: pd.DataFrame,
    path: Path = ANCHORS_PATH,
    now: pd.Timestamp | None = None,
) -> dict[tuple[str, str], MatchAnchor]:
    """Parse anchors.csv into {(match_key, book): MatchAnchor}.

    match_key is "<home_id> v <away_id>" in fixtures orientation, so a quote
    typed in either orientation lands on the same key. A duplicate
    (match, book) raises (which of two quotes is the anchor must be
    unambiguous).
    """
    now = now if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(df.columns) != _COLUMNS:
        raise LineError(f"{path} columns must be {_COLUMNS}, got {list(df.columns)}")
    if df.empty:
        return {}

    reg = registry()
    out: dict[tuple[str, str], MatchAnchor] = {}
    for i, row in enumerate(df.itertuples(index=False), start=2):
        where = f"{path.name} row {i}"
        ts = pd.Timestamp(str(row.ts_utc))
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        age = now - ts
        if age > MAX_AGE:
            raise LineError(
                f"{where}: anchor quote is stale ({age.components.days}d "
                f"{age.components.hours}h old) — re-enter today's 1X2 and delete old rows"
            )
        parts = [p.strip() for p in str(row.match).split(" v ")]
        if len(parts) != 2 or not all(parts):
            raise LineError(f"{where}: match must be '<home> v <away>', got {row.match!r}")
        typed_a, typed_b = (reg.resolve(p) for p in parts)
        match_date, home_id, away_id, neutral = resolve_fixture(typed_a, typed_b, fixtures)

        o_home, o_draw, o_away = (
            parse_odds(str(row.home_odds)),
            parse_odds(str(row.draw_odds)),
            parse_odds(str(row.away_odds)),
        )
        fair_a, fair_draw, fair_b = devig_1x2(o_home, o_draw, o_away)
        # Map the user's typed orientation (home_odds := typed_a) onto the
        # fixtures-table orientation.
        if typed_a == home_id:
            fp_home, fp_away = fair_a, fair_b
        else:
            fp_home, fp_away = fair_b, fair_a

        key = (f"{home_id} v {away_id}", str(row.book).strip())
        if key in out:
            raise LineError(f"{where}: duplicate anchor for {key[0]} at book {key[1]!r}")
        out[key] = MatchAnchor(
            ts=ts,
            match_date=match_date,
            home_id=home_id,
            away_id=away_id,
            neutral=neutral,
            fair_p_home=fp_home,
            fair_p_draw=fair_draw,
            fair_p_away=fp_away,
            book=str(row.book).strip(),
        )
    return out


def anchor_for(
    anchors: dict[tuple[str, str], MatchAnchor], match_key: str, book: str
) -> MatchAnchor | None:
    """The anchor to price a quote: same book preferred, else any book for
    the match (cross-book anchoring is allowed but the caller flags it)."""
    exact = anchors.get((match_key, book))
    if exact is not None:
        return exact
    same_match = [a for (mk, _), a in anchors.items() if mk == match_key]
    return same_match[0] if same_match else None


def load_snapshot_anchors(
    fixtures: pd.DataFrame,
    path: Path | None = None,
    now: pd.Timestamp | None = None,
) -> dict[str, MatchAnchor]:
    """Auto-anchors from the odds-snapshot store (D033): {match_key: anchor}.

    The latest non-stale snapshot per match, de-vigged to fixtures
    orientation, source-tagged SNAPSHOT_SOURCE. Best-effort: a snapshot for a
    played/absent fixture is skipped (not raised) — it is a fallback, used
    only when the user typed no anchors.csv row for the match.
    """
    from wc26.data.odds_api import SNAPSHOT_SOURCE, SNAPSHOTS_PATH, load_snapshots

    now = now if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    rows = load_snapshots(path if path is not None else SNAPSHOTS_PATH)
    latest: dict[frozenset[str], dict[str, str]] = {}
    for r in rows:
        pair = frozenset((r["home_id"], r["away_id"]))
        if pair not in latest or r["snapshot_ts"] > latest[pair]["snapshot_ts"]:
            latest[pair] = r

    out: dict[str, MatchAnchor] = {}
    for r in latest.values():
        ts = pd.Timestamp(r["snapshot_ts"])
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        if now - ts > MAX_AGE:
            continue  # stale snapshot — don't price off it
        try:
            match_date, home_id, away_id, neutral = resolve_fixture(
                r["home_id"], r["away_id"], fixtures
            )
        except LineError:
            continue  # played or absent fixture — skip, it's only a fallback
        fa, fdraw, fb = devig_1x2(
            float(r["home_odds"]), float(r["draw_odds"]), float(r["away_odds"])
        )
        fp_home, fp_away = (fa, fb) if r["home_id"] == home_id else (fb, fa)
        out[f"{home_id} v {away_id}"] = MatchAnchor(
            ts=ts,
            match_date=match_date,
            home_id=home_id,
            away_id=away_id,
            neutral=neutral,
            fair_p_home=fp_home,
            fair_p_draw=fdraw,
            fair_p_away=fp_away,
            book=SNAPSHOT_SOURCE,
        )
    return out


def latest_snapshot_1x2(
    home_id: str, away_id: str, path: Path | None = None
) -> tuple[float, float, str] | None:
    """Latest odds-snapshot 1X2 for a team pair, de-vigged & oriented to the
    GIVEN home_id (for settlement CLV — D033/#15).

    Returns (fair_p_home, fair_p_away, snapshot_ts) or None. Unlike
    load_snapshot_anchors this does NOT require an unplayed fixture: at settle
    time the match is played, and the latest pre-kickoff snapshot per match is
    its closing proxy. No staleness filter for the same reason (a bet settled
    days later still has a valid pre-kickoff close).
    """
    from wc26.data.odds_api import SNAPSHOTS_PATH, load_snapshots

    rows = load_snapshots(path if path is not None else SNAPSHOTS_PATH)
    pair = frozenset((home_id, away_id))
    matching = [r for r in rows if frozenset((r["home_id"], r["away_id"])) == pair]
    if not matching:
        return None
    latest = max(matching, key=lambda r: r["snapshot_ts"])
    fa, _, fb = devig_1x2(
        float(latest["home_odds"]), float(latest["draw_odds"]), float(latest["away_odds"])
    )
    fp_home, fp_away = (fa, fb) if latest["home_id"] == home_id else (fb, fa)
    return fp_home, fp_away, latest["snapshot_ts"]


def pick_anchor(
    manual: dict[tuple[str, str], MatchAnchor],
    snapshots: dict[str, MatchAnchor],
    match_key: str,
    book: str,
) -> tuple[MatchAnchor | None, str]:
    """Resolve the anchor for a quote and label its source.

    Priority: the book's own anchors.csv row -> another book's anchors.csv row
    (cross-book) -> the odds-snapshot fallback (D033) -> none. The label drives
    the edges display and the log-bet note.
    """
    same_book = manual.get((match_key, book))
    if same_book is not None:
        return same_book, "book"
    other = [a for (mk, _), a in manual.items() if mk == match_key]
    if other:
        return other[0], f"cross-book({other[0].book})"
    snap = snapshots.get(match_key)
    if snap is not None:
        return snap, "snapshot"
    return None, "none"
