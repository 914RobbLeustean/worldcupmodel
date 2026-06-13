"""The Odds API: h2h sanity check (PLAN 4.3, D007) + kickoff odds snapshots
(D033, backlog #6) — budgeted, optional.

Free tier = 500 credits/month; our self-imposed hard cap is
settings.odds_api.monthly_credit_budget (400 since D031). A persisted counter
(data/processed/odds_api_credits.json) is charged BEFORE every request —
attempts count, so a failing request can never burn the tier in a retry
loop. One call = regions x markets credits (one region; h2h = 1, h2h+totals
= 2).

Two uses, both market-consensus (averaged across books), never a single
book:
- fetch_h2h: a SANITY check of the model's 1X2 vs the live market (gate iii).
- fetch_odds_snapshot: a durable point-in-time capture of 1X2 (+ match
  totals) written append-only to data/odds_snapshots.csv. It is the fallback
  CLOSING anchor (so a missed manual capture no longer loses CLV) and an
  auto-anchor source for market-anchored pricing (D028/D032): markets with no
  hand-entered anchors.csv row fall back to the latest snapshot.
"""

import csv
import json
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

CREDITS_PATH = REPO_ROOT / "data" / "processed" / "odds_api_credits.json"
SNAPSHOTS_PATH = REPO_ROOT / "data" / "odds_snapshots.csv"  # durable, in git (append-only)
RAW_DIR = REPO_ROOT / "data" / "raw" / "odds_api"  # cached forever, git-ignored
SPORT_KEY = "soccer_fifa_world_cup"  # The Odds API sport key for WC 2026
BASE_URL = "https://api.the-odds-api.com/v4/sports"
SNAPSHOT_SOURCE = "the_odds_api_eu_avg"


class CreditBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class H2HQuote:
    """Average decimal h2h odds for one upcoming match (canonical team ids)."""

    home_id: str
    away_id: str
    home_odds: float
    draw_odds: float
    away_odds: float
    n_books: int


def charge_credits(cost: int, budget: int, path: Path = CREDITS_PATH) -> int:
    """Charge `cost` credits against this month's budget; return total used.

    Raises CreditBudgetExceeded BEFORE the caller makes the request. The
    counter resets on calendar-month rollover (UTC).
    """
    month = datetime.now(tz=UTC).strftime("%Y-%m")
    used = 0
    if path.exists():
        state: dict[str, Any] = json.loads(path.read_text())
        if state.get("month") == month:
            used = int(state["used"])
    if used + cost > budget:
        raise CreditBudgetExceeded(
            f"Odds API budget would be exceeded: {used} used + {cost} > {budget}/mo "
            f"hard cap (D007). Resets next month; raise the cap only via a "
            f"DECISIONS.md entry."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"month": month, "used": used + cost}, indent=1))
    return used + cost


def parse_h2h_events(events: list[dict[str, Any]]) -> list[H2HQuote]:
    """API events JSON -> per-match average decimal odds, strictly resolved.

    Unknown team names raise (fix the alias in config/teams.yaml — never
    loosen the check).
    """
    reg = registry()
    quotes: list[H2HQuote] = []
    for event in events:
        home_name, away_name = str(event["home_team"]), str(event["away_team"])
        home_id, away_id = reg.resolve(home_name), reg.resolve(away_name)
        sums = {"home": 0.0, "draw": 0.0, "away": 0.0}
        n_books = 0
        for book in event.get("bookmakers", []):
            h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
            if h2h is None:
                continue
            prices: dict[str, float] = {}
            for outcome in h2h["outcomes"]:
                name = str(outcome["name"])
                slot = "draw" if name == "Draw" else ("home" if name == home_name else "away")
                prices[slot] = float(outcome["price"])
            if set(prices) != {"home", "draw", "away"}:
                continue  # incomplete book, skip it (not the whole event)
            for slot, price in prices.items():
                sums[slot] += price
            n_books += 1
        if n_books == 0:
            continue
        quotes.append(
            H2HQuote(
                home_id=home_id,
                away_id=away_id,
                home_odds=sums["home"] / n_books,
                draw_odds=sums["draw"] / n_books,
                away_odds=sums["away"] / n_books,
                n_books=n_books,
            )
        )
    return quotes


def fetch_h2h(api_key: str, budget: int, credits_path: Path = CREDITS_PATH) -> list[H2HQuote]:
    """One budgeted live request: upcoming WC26 h2h averages (1 credit)."""
    charge_credits(1, budget, credits_path)
    query = urllib.parse.urlencode(
        {"regions": "eu", "markets": "h2h", "oddsFormat": "decimal", "apiKey": api_key}
    )
    url = f"{BASE_URL}/{SPORT_KEY}/odds/?{query}"
    with urllib.request.urlopen(url, timeout=30) as response:
        events: list[dict[str, Any]] = json.load(response)
    return parse_h2h_events(events)


# ── Kickoff odds snapshots (D033, backlog #6) ──────────────────────────────


@dataclass(frozen=True)
class MatchOddsSnapshot:
    """One match's market-averaged 1X2 (+ consensus match total) at fetch time.

    Odds are decimal averages across books (the de-vig is done on read, like
    lines.csv/anchors.csv). Totals fields are None when no book quoted a
    totals market for the event.
    """

    home_id: str
    away_id: str
    commence_time: str  # API kickoff (ISO 8601, UTC)
    n_books_h2h: int
    home_odds: float
    draw_odds: float
    away_odds: float
    n_books_totals: int
    total_line: float | None
    over_odds: float | None
    under_odds: float | None


_SNAPSHOT_COLUMNS = ["snapshot_ts", "source", *[f.name for f in fields(MatchOddsSnapshot)]]


def _consensus_total(
    per_book: list[tuple[float, float, float]],
) -> tuple[int, float | None, float | None, float | None]:
    """(n_books, line, over, under) at the modal main total across books.

    per_book is [(point, over_price, under_price)]; books that quote several
    points have already been reduced to their main pair (nearest 2.5). The
    consensus line is the most common point (ties -> nearest 2.5); over/under
    are averaged among the books quoting it.
    """
    if not per_book:
        return 0, None, None, None
    counts = Counter(round(p, 1) for p, _, _ in per_book)
    top = max(counts, key=lambda pt: (counts[pt], -abs(pt - 2.5)))
    at_line = [(o, u) for p, o, u in per_book if round(p, 1) == top]
    n = len(at_line)
    return n, top, sum(o for o, _ in at_line) / n, sum(u for _, u in at_line) / n


def _book_main_total(outcomes: list[dict[str, Any]]) -> tuple[float, float, float] | None:
    """A book's main (point, over, under) — the Over/Under pair nearest 2.5."""
    by_point: dict[float, dict[str, float]] = {}
    for o in outcomes:
        if "point" not in o:
            return None
        point = float(o["point"])
        side = str(o["name"]).lower()
        if side in ("over", "under"):
            by_point.setdefault(point, {})[side] = float(o["price"])
    complete = {p: d for p, d in by_point.items() if {"over", "under"} <= d.keys()}
    if not complete:
        return None
    point = min(complete, key=lambda p: abs(p - 2.5))
    return point, complete[point]["over"], complete[point]["under"]


def parse_snapshot_events(events: list[dict[str, Any]]) -> list[MatchOddsSnapshot]:
    """API events JSON -> per-match averaged 1X2 + consensus total.

    Unknown team names raise (alias drift, like parse_h2h_events). Events with
    no usable h2h are dropped (the 1X2 is the anchor; a snapshot without it is
    useless).
    """
    reg = registry()
    out: list[MatchOddsSnapshot] = []
    for event in events:
        home_name, away_name = str(event["home_team"]), str(event["away_team"])
        home_id, away_id = reg.resolve(home_name), reg.resolve(away_name)
        h2h_sums = {"home": 0.0, "draw": 0.0, "away": 0.0}
        n_h2h = 0
        totals_books: list[tuple[float, float, float]] = []
        for book in event.get("bookmakers", []):
            markets = {m.get("key"): m for m in book.get("markets", [])}
            h2h = markets.get("h2h")
            if h2h is not None:
                prices: dict[str, float] = {}
                for outcome in h2h["outcomes"]:
                    name = str(outcome["name"])
                    slot = "draw" if name == "Draw" else ("home" if name == home_name else "away")
                    prices[slot] = float(outcome["price"])
                if set(prices) == {"home", "draw", "away"}:
                    for slot, price in prices.items():
                        h2h_sums[slot] += price
                    n_h2h += 1
            totals = markets.get("totals")
            if totals is not None:
                main = _book_main_total(totals["outcomes"])
                if main is not None:
                    totals_books.append(main)
        if n_h2h == 0:
            continue
        n_tot, line, over, under = _consensus_total(totals_books)
        out.append(
            MatchOddsSnapshot(
                home_id=home_id,
                away_id=away_id,
                commence_time=str(event.get("commence_time", "")),
                n_books_h2h=n_h2h,
                home_odds=h2h_sums["home"] / n_h2h,
                draw_odds=h2h_sums["draw"] / n_h2h,
                away_odds=h2h_sums["away"] / n_h2h,
                n_books_totals=n_tot,
                total_line=line,
                over_odds=over,
                under_odds=under,
            )
        )
    return out


def append_snapshots(
    snapshots: list[MatchOddsSnapshot], snapshot_ts: str, path: Path = SNAPSHOTS_PATH
) -> None:
    """Append snapshot rows (append-only, like the ledger; in git)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(",".join(_SNAPSHOT_COLUMNS) + "\n")
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        for s in snapshots:
            row = {"snapshot_ts": snapshot_ts, "source": SNAPSHOT_SOURCE, **s.__dict__}
            w.writerow(["" if row[c] is None else row[c] for c in _SNAPSHOT_COLUMNS])


def fetch_odds_snapshot(
    api_key: str,
    budget: int,
    credits_path: Path = CREDITS_PATH,
    raw_dir: Path = RAW_DIR,
) -> tuple[list[MatchOddsSnapshot], str]:
    """One budgeted request: upcoming WC26 1X2 + totals (2 credits).

    Caches the raw JSON forever (audit/re-parse) and returns the parsed
    snapshots plus the UTC fetch timestamp. The caller persists them via
    append_snapshots.
    """
    snapshot_ts = datetime.now(tz=UTC).isoformat(timespec="seconds")
    charge_credits(2, budget, credits_path)
    query = urllib.parse.urlencode(
        {"regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal", "apiKey": api_key}
    )
    url = f"{BASE_URL}/{SPORT_KEY}/odds/?{query}"
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read()
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{SPORT_KEY}_{snapshot_ts.replace(':', '')}.json").write_bytes(raw)
    events: list[dict[str, Any]] = json.loads(raw)
    return parse_snapshot_events(events), snapshot_ts


def load_snapshots(path: Path = SNAPSHOTS_PATH) -> list[dict[str, Any]]:
    """Read the snapshot store as raw dict rows (newest-relevant filtering is
    the caller's job). Empty list if the store does not exist yet."""
    if not path.exists():
        return []
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if rows and list(rows[0].keys()) != _SNAPSHOT_COLUMNS:
        raise ValueError(f"{path} columns must be {_SNAPSHOT_COLUMNS}, got {list(rows[0].keys())}")
    return rows
