"""anchors.csv parsing + the market-anchored pricing glue (D028/D032).

Anchors carry the book's 1X2 per match; team totals price off the DC grid
solved to reproduce it. These tests pin the parse, the de-vig, the
orientation mapping (a flipped entry maps to fixtures orientation), the
hard guards, and that the anchored P(over) equals a direct solve.
"""

from pathlib import Path

import pandas as pd
import pytest

from wc26.data.odds_api import MatchOddsSnapshot, append_snapshots
from wc26.markets.anchors import (
    MatchAnchor,
    anchor_for,
    devig_1x2,
    load_anchors,
    load_snapshot_anchors,
    pick_anchor,
)
from wc26.markets.lines import LineError

NOW = pd.Timestamp("2026-06-18T12:00:00")
HEADER = "ts_utc,match,home_odds,draw_odds,away_odds,book\n"

FIXTURES = pd.DataFrame(
    {
        "date": [pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-11")],
        "home_id": ["mexico", "mexico"],
        "away_id": ["south_korea", "south_africa"],
        "neutral": [False, False],
        "played": [False, True],
    }
)


def _write(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "anchors.csv"
    path.write_text(HEADER + "".join(r + "\n" for r in rows))
    return path


def test_devig_1x2_normalizes_to_one() -> None:
    p_home, p_draw, p_away = devig_1x2(2.12, 3.30, 4.09)
    assert p_home + p_draw + p_away == pytest.approx(1.0)
    assert p_home > p_away  # 2.12 is the favorite


def test_anchor_parse_and_orientation(tmp_path: Path) -> None:
    """Match typed in REVERSED order: home_odds is for the typed-first team
    (south_korea here), which is the fixtures AWAY side, so it must land on
    fair_p_away after the flip."""
    path = _write(
        tmp_path,
        ["2026-06-18T10:00:00,Korea Republic v Mexico,5.00,3.60,1.70,bet365"],
    )
    anchors = load_anchors(FIXTURES, path, now=NOW)
    assert list(anchors.keys()) == [("mexico v south_korea", "bet365")]
    a = anchors[("mexico v south_korea", "bet365")]
    # typed home = south_korea @ 5.00 (longshot) -> fixtures AWAY prob is small
    assert a.fair_p_away < a.fair_p_home
    assert a.fair_p_home + a.fair_p_draw + a.fair_p_away == pytest.approx(1.0)
    assert a.home_id == "mexico" and a.away_id == "south_korea"


def test_anchor_orientation_straight(tmp_path: Path) -> None:
    """Typed in fixtures order: home_odds (mexico) is the favorite."""
    path = _write(tmp_path, ["2026-06-18T10:00:00,Mexico v South Korea,1.70,3.60,5.00,bet365"])
    a = load_anchors(FIXTURES, path, now=NOW)[("mexico v south_korea", "bet365")]
    assert a.fair_p_home > a.fair_p_away


def test_stale_anchor_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, ["2026-06-15T10:00:00,Mexico v South Korea,1.70,3.60,5.00,bet365"])
    with pytest.raises(LineError, match="stale"):
        load_anchors(FIXTURES, path, now=NOW)


def test_duplicate_anchor_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            "2026-06-18T10:00:00,Mexico v South Korea,1.70,3.60,5.00,bet365",
            "2026-06-18T11:00:00,Mexico v South Korea,1.72,3.55,4.90,bet365",
        ],
    )
    with pytest.raises(LineError, match="duplicate anchor"):
        load_anchors(FIXTURES, path, now=NOW)


def test_played_match_anchor_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, ["2026-06-18T10:00:00,Mexico v South Africa,1.70,3.60,5.00,bet365"])
    with pytest.raises(LineError, match="already played"):
        load_anchors(FIXTURES, path, now=NOW)


def test_missing_file_is_empty() -> None:
    assert load_anchors(FIXTURES, Path("/nonexistent/anchors.csv"), now=NOW) == {}


def test_anchor_for_prefers_same_book_then_falls_back(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            "2026-06-18T10:00:00,Mexico v South Korea,1.70,3.60,5.00,bet365",
            "2026-06-18T10:00:00,Mexico v South Korea,1.72,3.55,4.90,superbet",
        ],
    )
    anchors = load_anchors(FIXTURES, path, now=NOW)
    assert anchor_for(anchors, "mexico v south_korea", "superbet").book == "superbet"
    assert anchor_for(anchors, "mexico v south_korea", "bet365").book == "bet365"
    # cross-book fallback: a book with no anchor gets some match anchor, not None
    assert anchor_for(anchors, "mexico v south_korea", "pinnacle") is not None
    assert anchor_for(anchors, "canada v bosnia", "bet365") is None


def test_anchored_p_over_matches_direct_solve(tmp_path: Path) -> None:
    """The CLI glue must reproduce a direct market_anchored_grid solve."""
    from wc26.markets.lines import TwoWayLine
    from wc26.models.market_anchor import market_anchored_grid
    from wc26.models.team_totals import goal_marginals, p_over

    path = _write(tmp_path, ["2026-06-18T10:00:00,Mexico v South Korea,1.70,3.60,5.00,bet365"])
    anchor = load_anchors(FIXTURES, path, now=NOW)[("mexico v south_korea", "bet365")]
    grid = market_anchored_grid(anchor.fair_p_home, anchor.fair_p_away, rho=-0.05)
    home_dist, _ = goal_marginals(grid)
    expected = p_over(home_dist, 1.5)

    from wc26.cli import _anchored_p_over

    class _Params:
        rho = -0.05
        version = "goal_engine 2026-06-14 @abcdef0"

    quote = TwoWayLine(
        ts=NOW,
        match_date=pd.Timestamp("2026-06-18"),
        home_id="mexico",
        away_id="south_korea",
        neutral=False,
        team_id="mexico",
        market="team_total:mexico",
        line=1.5,
        over_odds=2.0,
        under_odds=1.8,
        book="bet365",
    )
    got, version = _anchored_p_over(_Params(), quote, anchor)  # type: ignore[arg-type]
    assert got == pytest.approx(expected)
    assert version.startswith("anchor+")


# ── snapshot fallback anchors (D033) ───────────────────────────────────────


def test_load_snapshot_anchors_skips_played_and_stale(tmp_path: Path) -> None:
    path = tmp_path / "odds_snapshots.csv"
    append_snapshots(
        [
            # unplayed fixture -> becomes an anchor
            MatchOddsSnapshot(
                "mexico",
                "south_korea",
                "2026-06-18T18:00:00Z",
                5,
                1.70,
                3.60,
                5.00,
                3,
                2.5,
                1.9,
                1.9,
            ),
            # played fixture (mexico v south_africa) -> skipped, not raised
            MatchOddsSnapshot(
                "mexico",
                "south_africa",
                "2026-06-11T18:00:00Z",
                5,
                1.50,
                4.00,
                6.00,
                0,
                None,
                None,
                None,
            ),
        ],
        "2026-06-18T08:00:00+00:00",
        path,
    )
    anchors = load_snapshot_anchors(FIXTURES, path, now=NOW)
    assert set(anchors) == {"mexico v south_korea"}
    a = anchors["mexico v south_korea"]
    assert a.fair_p_home > a.fair_p_away  # mexico 1.70 favored
    assert a.book == "the_odds_api_eu_avg"

    # a snapshot older than 24h is not priced off
    stale = load_snapshot_anchors(FIXTURES, path, now=pd.Timestamp("2026-06-20T00:00:00"))
    assert stale == {}


def test_load_snapshot_anchors_orientation_flip(tmp_path: Path) -> None:
    """Snapshot stored with home=south_korea (API order) maps to the fixtures
    AWAY side."""
    path = tmp_path / "odds_snapshots.csv"
    append_snapshots(
        [
            MatchOddsSnapshot(
                "south_korea",
                "mexico",
                "2026-06-18T18:00:00Z",
                5,
                5.00,
                3.60,
                1.70,
                0,
                None,
                None,
                None,
            )
        ],
        "2026-06-18T08:00:00+00:00",
        path,
    )
    a = load_snapshot_anchors(FIXTURES, path, now=NOW)["mexico v south_korea"]
    assert a.home_id == "mexico" and a.fair_p_home > a.fair_p_away  # mexico (1.70) still favored


def _anchor(book: str) -> MatchAnchor:
    return MatchAnchor(
        ts=NOW,
        match_date=pd.Timestamp("2026-06-18"),
        home_id="mexico",
        away_id="south_korea",
        neutral=False,
        fair_p_home=0.5,
        fair_p_draw=0.3,
        fair_p_away=0.2,
        book=book,
    )


def test_pick_anchor_priority() -> None:
    mk = "mexico v south_korea"
    manual = {(mk, "superbet"): _anchor("superbet"), (mk, "bet365"): _anchor("bet365")}
    snaps = {mk: _anchor("the_odds_api_eu_avg")}

    assert pick_anchor(manual, snaps, mk, "superbet") == (manual[(mk, "superbet")], "book")
    a, label = pick_anchor(manual, snaps, mk, "pinnacle")  # no same-book manual
    assert label == "cross-book(superbet)" and a.book == "superbet"
    a, label = pick_anchor({}, snaps, mk, "superbet")  # no manual at all
    assert label == "snapshot" and a.book == "the_odds_api_eu_avg"
    assert pick_anchor({}, {}, mk, "superbet") == (None, "none")
