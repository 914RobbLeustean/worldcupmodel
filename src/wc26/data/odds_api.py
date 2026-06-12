"""The Odds API h2h sanity check (PLAN 4.3, D007) — budgeted, optional.

Free tier = 500 credits/month; our self-imposed hard cap is
settings.odds_api.monthly_credit_budget (150). A persisted counter
(data/processed/odds_api_credits.json) is charged BEFORE every request —
attempts count, so a failing request can never burn the tier in a retry
loop. One call = regions x markets = 1 credit (one region, h2h only).

This is a SANITY check of the model's 1X2 vs the live market (like backtest
gate iii), never a pricing path: prop lines stay manual (D007).
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

CREDITS_PATH = REPO_ROOT / "data" / "processed" / "odds_api_credits.json"
SPORT_KEY = "soccer_fifa_world_cup"  # The Odds API sport key for WC 2026
BASE_URL = "https://api.the-odds-api.com/v4/sports"


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
