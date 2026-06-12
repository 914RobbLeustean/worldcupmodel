"""Market odds parsing on frozen HTML, plus source-verification tests that
run when the cached raw downloads are present (they are immutable)."""

from pathlib import Path

import pandas as pd
import pytest

from wc26.data.market_odds import (
    FOOTBALL_DATA_XLSX,
    ODDS_RAW,
    PROCESSED_DIR,
    football_data_90min_results,
    parse_betexplorer_results,
)

# Two real rows from the BetExplorer Euro 2024 results page (knockout AJAX
# fragment), frozen 2026-06-12. Winner's odd is wrapped in extra spans.
BETEXPLORER_FRAGMENT = (
    Path(__file__).parent / "fixtures" / "betexplorer_fragment.html"
).read_text()


def test_parse_betexplorer_fragment() -> None:
    df = parse_betexplorer_results(BETEXPLORER_FRAGMENT, "UEFA Euro")
    assert len(df) == 2
    final = df.iloc[0]
    assert (final["home_id"], final["away_id"]) == ("spain", "england")
    assert final["date"] == pd.Timestamp("2024-07-14")
    assert (final["odds_home"], final["odds_draw"], final["odds_away"]) == (2.41, 2.80, 3.57)
    semi = df.iloc[1]
    assert (semi["odds_home"], semi["odds_draw"], semi["odds_away"]) == (3.18, 2.80, 2.63)


needs_processed = pytest.mark.skipif(
    not (PROCESSED_DIR / "market_odds.parquet").exists(),
    reason="market_odds.parquet not built (wc26 backtest builds it)",
)
needs_raw_xlsx = pytest.mark.skipif(
    not FOOTBALL_DATA_XLSX.exists(), reason="football-data xlsx not downloaded"
)


@needs_processed
def test_known_matches_verify_across_sources() -> None:
    """The 2-3 known-match verification required before trusting a source.

    football-data.co.uk averages vs independently published BetExplorer
    averages for the same matches (cross-checked 2026-06-12, ~1.5% apart).
    """
    odds = pd.read_parquet(PROCESSED_DIR / "market_odds.parquet")

    def row(home: str, away: str, date: str) -> pd.Series:
        hit = odds[
            (odds["home_id"] == home)
            & (odds["away_id"] == away)
            & (odds["date"] == pd.Timestamp(date))
        ]
        assert len(hit) == 1, f"{home} v {away} {date}: {len(hit)} rows"
        return hit.iloc[0]

    # WC22 final (football-data avg; BetExplorer shows 2.67/3.13/2.86)
    final22 = row("argentina", "france", "2022-12-18")
    assert final22["odds_home"] == pytest.approx(2.63, abs=0.1)
    assert final22["odds_draw"] == pytest.approx(3.12, abs=0.1)
    assert final22["odds_away"] == pytest.approx(2.84, abs=0.1)
    # WC18 opener
    opener18 = row("russia", "saudi_arabia", "2018-06-14")
    assert opener18["odds_home"] == pytest.approx(1.46, abs=0.05)
    # Euro 2024 final (BetExplorer)
    final24 = row("spain", "england", "2024-07-14")
    assert final24["odds_home"] == pytest.approx(2.41, abs=0.05)
    assert final24["odds_away"] == pytest.approx(3.57, abs=0.05)


@needs_processed
def test_expected_tournament_coverage() -> None:
    odds = pd.read_parquet(PROCESSED_DIR / "market_odds.parquet")
    assert odds["tournament"].value_counts().to_dict() == {
        "FIFA World Cup": 128,
        "UEFA Euro": 51,
        "Copa América": 32,
    }
    assert odds[["odds_home", "odds_draw", "odds_away"]].min().min() > 1.0


@needs_raw_xlsx
def test_d012_extra_time_matches_were_draws_at_90() -> None:
    """football-data publishes the true 90' score separately (HGFT/AGFT):
    every match our pipeline flags extra_time must have been level at 90'.
    This independently validates resolving ET matches as draws in the
    backtest (D012)."""
    if not (PROCESSED_DIR / "match_stats.parquet").exists():
        pytest.skip("match_stats.parquet not built")
    truth = football_data_90min_results()
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    et = stats[stats["extra_time"] & (stats["tournament"] == "FIFA World Cup")]
    assert len(et) == 10  # 5 each at WC18/WC22
    checked = 0
    for row in et.itertuples(index=False):
        hits = truth[
            (
                ((truth["home_id"] == row.home_id) & (truth["away_id"] == row.away_id))
                | ((truth["home_id"] == row.away_id) & (truth["away_id"] == row.home_id))
            )
            & ((truth["date"] - pd.Timestamp(row.date)).abs() <= pd.Timedelta(days=1))
        ]
        assert len(hits) == 1
        assert hits.iloc[0]["home_score_90"] == hits.iloc[0]["away_score_90"]
        checked += 1
    assert checked == 10


def test_live_odds_snapshot_parses_if_present() -> None:
    from wc26.data.market_odds import fetch_wc26_live_odds, latest_wc26_snapshot_date

    day = latest_wc26_snapshot_date()
    if day is None:
        pytest.skip("no cached WC26 live odds snapshot")
    live = fetch_wc26_live_odds(day)  # cache hit — no network
    assert len(live) > 0
    assert live[["odds_home", "odds_draw", "odds_away"]].min().min() > 1.0
    assert ODDS_RAW.joinpath(f"betexplorer_wc26_fixtures_{day}.html").exists()
