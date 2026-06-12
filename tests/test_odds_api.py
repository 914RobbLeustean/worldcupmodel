"""Odds API budget counter (D007 hard cap) and h2h response parsing.

No network anywhere in here — fetch_h2h is exercised only through its parts
(charge_credits + parse_h2h_events)."""

import json
from pathlib import Path

import pytest

from wc26.data.odds_api import (
    CreditBudgetExceeded,
    charge_credits,
    parse_h2h_events,
)
from wc26.data.teams import UnknownTeamError


def test_credits_accumulate_and_persist(tmp_path: Path) -> None:
    path = tmp_path / "credits.json"
    assert charge_credits(1, budget=150, path=path) == 1
    assert charge_credits(2, budget=150, path=path) == 3
    state = json.loads(path.read_text())
    assert state["used"] == 3


def test_hard_cap_refuses_before_spending(tmp_path: Path) -> None:
    path = tmp_path / "credits.json"
    charge_credits(149, budget=150, path=path)
    with pytest.raises(CreditBudgetExceeded, match="150/mo"):
        charge_credits(2, budget=150, path=path)
    # the failed attempt must NOT have been recorded
    assert json.loads(path.read_text())["used"] == 149
    # but the remaining credit is still spendable
    assert charge_credits(1, budget=150, path=path) == 150


def test_counter_resets_on_month_rollover(tmp_path: Path) -> None:
    path = tmp_path / "credits.json"
    path.write_text(json.dumps({"month": "1999-01", "used": 150}))
    assert charge_credits(1, budget=150, path=path) == 1


EVENT = {
    "home_team": "United States",
    "away_team": "Paraguay",
    "bookmakers": [
        {
            "key": "books_a",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "United States", "price": 2.0},
                        {"name": "Paraguay", "price": 4.0},
                        {"name": "Draw", "price": 3.0},
                    ],
                }
            ],
        },
        {
            "key": "books_b",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "United States", "price": 2.2},
                        {"name": "Paraguay", "price": 3.8},
                        {"name": "Draw", "price": 3.2},
                    ],
                }
            ],
        },
        {"key": "incomplete", "markets": [{"key": "h2h", "outcomes": []}]},
    ],
}


def test_parse_h2h_averages_and_resolves() -> None:
    (quote,) = parse_h2h_events([EVENT])
    assert (quote.home_id, quote.away_id) == ("united_states", "paraguay")
    assert quote.n_books == 2  # incomplete book skipped, event kept
    assert quote.home_odds == pytest.approx(2.1)
    assert quote.draw_odds == pytest.approx(3.1)
    assert quote.away_odds == pytest.approx(3.9)


def test_parse_h2h_unknown_team_raises() -> None:
    bad = dict(EVENT, home_team="Ruritania")
    with pytest.raises(UnknownTeamError):
        parse_h2h_events([bad])


def test_parse_h2h_event_without_books_is_dropped() -> None:
    assert parse_h2h_events([dict(EVENT, bookmakers=[])]) == []
