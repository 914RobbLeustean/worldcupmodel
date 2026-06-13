"""Odds API budget counter (D007 hard cap) and h2h response parsing.

No network anywhere in here — fetch_h2h is exercised only through its parts
(charge_credits + parse_h2h_events)."""

import json
from pathlib import Path

import pytest

from wc26.data.odds_api import (
    CreditBudgetExceeded,
    MatchOddsSnapshot,
    append_snapshots,
    charge_credits,
    load_snapshots,
    parse_h2h_events,
    parse_snapshot_events,
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


# ── snapshot parsing + store (D033) ────────────────────────────────────────


def _book(name: str, h_o: float, d_o: float, a_o: float, total: tuple | None = None) -> dict:
    markets = [
        {
            "key": "h2h",
            "outcomes": [
                {"name": "United States", "price": h_o},
                {"name": "Draw", "price": d_o},
                {"name": "Paraguay", "price": a_o},
            ],
        }
    ]
    if total is not None:
        point, over, under = total
        markets.append(
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": over, "point": point},
                    {"name": "Under", "price": under, "point": point},
                ],
            }
        )
    return {"key": name, "markets": markets}


def test_parse_snapshot_h2h_and_consensus_total() -> None:
    event = {
        "home_team": "United States",
        "away_team": "Paraguay",
        "commence_time": "2026-06-13T01:00:00Z",
        "bookmakers": [
            _book("a", 2.0, 3.0, 4.0, total=(2.5, 1.90, 1.95)),
            _book("b", 2.2, 3.2, 3.8, total=(2.5, 2.00, 1.85)),
            _book("c", 2.1, 3.1, 3.9, total=(3.0, 2.40, 1.55)),  # off-consensus line
        ],
    }
    (s,) = parse_snapshot_events([event])
    assert (s.home_id, s.away_id) == ("united_states", "paraguay")
    assert s.n_books_h2h == 3
    assert s.home_odds == pytest.approx((2.0 + 2.2 + 2.1) / 3)
    # consensus total = 2.5 (two books), the 3.0 book is excluded from the avg
    assert s.total_line == pytest.approx(2.5)
    assert s.n_books_totals == 2
    assert s.over_odds == pytest.approx((1.90 + 2.00) / 2)


def test_parse_snapshot_without_totals_is_none() -> None:
    event = {
        "home_team": "United States",
        "away_team": "Paraguay",
        "commence_time": "",
        "bookmakers": [_book("a", 2.0, 3.0, 4.0)],
    }
    (s,) = parse_snapshot_events([event])
    assert s.total_line is None and s.over_odds is None and s.n_books_totals == 0


def test_snapshot_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "odds_snapshots.csv"
    snaps = [
        MatchOddsSnapshot(
            "united_states",
            "paraguay",
            "2026-06-13T01:00:00Z",
            3,
            2.1,
            3.1,
            3.9,
            2,
            2.5,
            1.95,
            1.90,
        ),
        MatchOddsSnapshot(
            "brazil", "morocco", "2026-06-13T18:00:00Z", 5, 2.3, 3.1, 3.4, 0, None, None, None
        ),
    ]
    append_snapshots(snaps, "2026-06-13T00:30:00+00:00", path)
    append_snapshots(snaps[:1], "2026-06-13T00:55:00+00:00", path)  # later capture, append-only
    rows = load_snapshots(path)
    assert len(rows) == 3
    assert rows[0]["home_id"] == "united_states"
    assert rows[0]["source"] == "the_odds_api_eu_avg"
    assert rows[1]["total_line"] == ""  # None serialized blank
    # the file is append-only: first two rows are the first call, untouched
    assert rows[2]["snapshot_ts"] == "2026-06-13T00:55:00+00:00"
