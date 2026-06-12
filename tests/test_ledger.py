"""Append-only ledger (D006): schema, append discipline, 90' settlement (D004),
hand-computed CLV, and the clv-report aggregation."""

from pathlib import Path

import pandas as pd
import pytest

from wc26.markets.ledger import (
    COLUMNS,
    LEDGER_PATH,
    BetRow,
    append_row,
    clv_report,
    latest_view,
    next_bet_id,
    read_ledger,
    settle_bet,
)


def _bet(bet_id: str = "B0001", **overrides: object) -> BetRow:
    base: dict[str, object] = {
        "bet_id": bet_id,
        "ts_utc": "2026-06-18T12:00:00+00:00",
        "match": "mexico v south_korea",
        "match_date": "2026-06-18",
        "market": "team_total:south_korea",
        "line": 1.5,
        "side": "over",
        "odds_taken": 1.91,
        "stake": 15.0,
        "model_prob": 0.58,
        "model_version": "goal_engine 2026-06-13 @f355f46",
        "edge": 0.08,
        "book": "bet365",
        "status": "open",
    }
    base.update(overrides)
    return BetRow(**base)  # type: ignore[arg-type]


def test_repo_ledger_header_is_canonical() -> None:
    """Schema test required by PLAN 4.2: the real ledger file must carry
    exactly the canonical columns (and reading it must validate)."""
    with LEDGER_PATH.open() as f:
        assert f.readline().strip() == ",".join(COLUMNS)
    read_ledger(LEDGER_PATH)


def test_append_only_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    append_row(_bet(), path)
    before = path.read_bytes()

    settlement = settle_bet(
        side="over",
        line=1.5,
        goals_90=2,
        odds_taken=1.91,
        stake=15.0,
        closing_over_odds=1.70,
        closing_under_odds=2.20,
    )
    append_row(
        _bet(
            status="settled",
            closing_over_odds=1.70,
            closing_under_odds=2.20,
            clv=settlement.clv,
            goals_90=2,
            result=settlement.result,
            pnl=settlement.pnl,
        ),
        path,
    )
    after = path.read_bytes()
    # append-only: prior content is untouched, byte for byte (D006)
    assert after.startswith(before)

    history = read_ledger(path)
    assert len(history) == 2
    current = latest_view(history)
    assert len(current) == 1
    assert current.iloc[0]["status"] == "settled"
    assert current.iloc[0]["result"] == "won"


def test_append_refuses_foreign_header(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    path.write_text("bet_id,whatever\n")
    with pytest.raises(ValueError, match="append-only"):
        append_row(_bet(), path)


def test_read_refuses_wrong_columns(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    path.write_text("bet_id,whatever\n")
    with pytest.raises(ValueError, match="columns"):
        read_ledger(path)


def test_bet_ids_increment(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    append_row(_bet("B0001"), path)
    append_row(_bet("B0002"), path)
    assert next_bet_id(read_ledger(path)) == "B0003"
    assert next_bet_id(pd.DataFrame()) == "B0001"


def test_hand_computed_settlement_and_clv() -> None:
    """Hand-derived: bet over 1.5 @ 1.91, stake 15; closing 1.70 / 2.20.

    closing implied: 1/1.70 = 10/17, 1/2.20 = 5/11; sum = 195/187
    fair closing P(over) = (10/17) / (195/187) = 110/195 = 22/39 = 0.5641026
    CLV = 1.91 * 22/39 - 1 = +0.0774359
    goals_90 = 2 > 1.5 -> won; pnl = 15 * 0.91 = +13.65
    """
    s = settle_bet(
        side="over",
        line=1.5,
        goals_90=2,
        odds_taken=1.91,
        stake=15.0,
        closing_over_odds=1.70,
        closing_under_odds=2.20,
    )
    assert s.result == "won"
    assert s.pnl == pytest.approx(13.65)
    assert s.fair_closing_p == pytest.approx(22.0 / 39.0, abs=1e-12)
    assert s.clv == pytest.approx(1.91 * 22.0 / 39.0 - 1.0, abs=1e-12)


def test_settlement_is_90_minutes_only() -> None:
    """D004: a knockout that finished 2-1 for the team AFTER extra time but
    1-1 after 90' settles as a LOSS for over 1.5 — the 90' count is what the
    caller must pass in (the CLI refuses ET matches' stored scores)."""
    s = settle_bet(
        side="over",
        line=1.5,
        goals_90=1,  # the 90-minute count, not the 120-minute one
        odds_taken=1.91,
        stake=15.0,
        closing_over_odds=1.91,
        closing_under_odds=1.91,
    )
    assert s.result == "lost"
    assert s.pnl == pytest.approx(-15.0)


def test_under_side_settlement() -> None:
    s = settle_bet(
        side="under",
        line=2.5,
        goals_90=2,
        odds_taken=2.05,
        stake=10.0,
        closing_over_odds=1.91,
        closing_under_odds=1.91,
    )
    assert s.result == "won"
    assert s.pnl == pytest.approx(10.5)
    assert s.fair_closing_p == pytest.approx(0.5)
    assert s.clv == pytest.approx(0.025)


def test_settle_rejects_whole_line_and_bad_side() -> None:
    with pytest.raises(ValueError, match="half-integer"):
        settle_bet("over", 2.0, 2, 1.91, 10.0, 1.91, 1.91)
    with pytest.raises(ValueError, match="side"):
        settle_bet("middle", 1.5, 2, 1.91, 10.0, 1.91, 1.91)


def test_clv_report_aggregates_by_market(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    append_row(_bet("B0001"), path)
    append_row(
        _bet(
            "B0001",
            status="settled",
            closing_over_odds=1.70,
            closing_under_odds=2.20,
            clv=0.0774359,
            goals_90=2,
            result="won",
            pnl=13.65,
        ),
        path,
    )
    append_row(_bet("B0002", side="under", model_prob=0.55), path)  # stays open
    history = read_ledger(path)
    report = clv_report(history)

    assert list(report["market"]) == ["team_total", "TOTAL"]
    total = report[report["market"] == "TOTAL"].iloc[0]
    assert total["bets"] == 1  # open bets are excluded
    assert total["pnl"] == pytest.approx(13.65)
    assert total["roi"] == pytest.approx(13.65 / 15.0)
    assert total["mean_clv"] == pytest.approx(0.0774359)
    assert total["win_rate"] == pytest.approx(1.0)


def test_clv_report_empty_when_nothing_settled(tmp_path: Path) -> None:
    path = tmp_path / "bets.csv"
    append_row(_bet(), path)
    assert clv_report(read_ledger(path)).empty


def _tables(extra_time: bool, with_result: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-29")],  # ESPN UTC date, fixture is 06-28 (D013)
            "home_id": ["mexico"],
            "away_id": ["south_korea"],
            "extra_time": [extra_time],
        }
    )
    results = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-28")],
            "home_id": ["mexico"],
            "away_id": ["south_korea"],
            "home_score": [2],
            "away_score": [1],
        }
    )
    if not with_result:
        results = results.iloc[0:0]
    return stats, results


def test_settle_reads_90_minute_goals_from_results() -> None:
    from wc26.cli import goals_90_from_tables

    stats, results = _tables(extra_time=False, with_result=True)
    date = pd.Timestamp("2026-06-28")
    assert goals_90_from_tables(stats, results, date, "mexico", "south_korea", "mexico") == 2
    assert goals_90_from_tables(stats, results, date, "mexico", "south_korea", "south_korea") == 1


def test_settle_refuses_extra_time_match_without_goals_flag() -> None:
    """PLAYBOOK §2 / D012: stored ET scores are 120' — auto-read must refuse."""
    from wc26.cli import SettleDataError, goals_90_from_tables

    stats, results = _tables(extra_time=True, with_result=True)
    with pytest.raises(SettleDataError, match="EXTRA TIME"):
        goals_90_from_tables(
            stats, results, pd.Timestamp("2026-06-28"), "mexico", "south_korea", "mexico"
        )


def test_settle_refuses_when_result_not_landed() -> None:
    from wc26.cli import SettleDataError, goals_90_from_tables

    stats, results = _tables(extra_time=False, with_result=False)
    with pytest.raises(SettleDataError, match="not in the results table"):
        goals_90_from_tables(
            stats, results, pd.Timestamp("2026-06-28"), "mexico", "south_korea", "mexico"
        )
