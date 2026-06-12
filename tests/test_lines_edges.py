"""lines.csv parsing, the Phase 4 hard guards, and the hand-computed
de-vig + edge fixture (PLAN verification requirement)."""

from pathlib import Path

import pandas as pd
import pytest

from wc26.data.teams import UnknownTeamError
from wc26.markets.edges import devig_two_way, evaluate, rank
from wc26.markets.lines import LineError, TwoWayLine, load_lines

NOW = pd.Timestamp("2026-06-18T12:00:00")
HEADER = "ts_utc,match,market,line,side,odds,book\n"

FIXTURES = pd.DataFrame(
    {
        "date": [pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-11")],
        "home_id": ["mexico", "mexico"],
        "away_id": ["south_korea", "south_africa"],
        "neutral": [False, False],
        "played": [False, True],
    }
)


def write_lines(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "lines.csv"
    path.write_text(HEADER + "".join(r + "\n" for r in rows))
    return path


def test_load_lines_happy_path(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        [
            # aliases + reversed match order + American odds, all normalized
            "2026-06-18T10:00:00,Korea Republic v Mexico,"
            "team_total:Korea Republic,1.5,over,-110,bet365",
            "2026-06-18T10:00:00,Korea Republic v Mexico,"
            "team_total:Korea Republic,1.5,under,1.87,bet365",
        ],
    )
    (quote,) = load_lines(FIXTURES, path, now=NOW)
    assert (quote.home_id, quote.away_id) == ("mexico", "south_korea")  # fixture order
    assert quote.neutral is False
    assert quote.market == "team_total:south_korea"
    assert quote.over_odds == pytest.approx(1.0 + 100.0 / 110.0)
    assert quote.under_odds == pytest.approx(1.87)


def test_quarantined_markets_are_refused(tmp_path: Path) -> None:
    cases = {
        "match_total": "D019",
        "corners": "D021",
        "cards": "D021",
    }
    for market, decision in cases.items():
        path = write_lines(
            tmp_path,
            [f"2026-06-18T10:00:00,Mexico v South Korea,{market},9.5,over,1.91,bet365"],
        )
        with pytest.raises(LineError, match=decision):
            load_lines(FIXTURES, path, now=NOW)


def test_unknown_market_lists_cleared_ones(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Mexico v South Korea,btts,0.5,over,1.91,bet365"],
    )
    with pytest.raises(LineError, match="team_total"):
        load_lines(FIXTURES, path, now=NOW)


def test_match_without_prediction_is_refused(tmp_path: Path) -> None:
    # Spain v France is a real team pair but not a WC26 fixture in this table
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Spain v France,team_total:Spain,1.5,over,1.91,bet365"],
    )
    with pytest.raises(LineError, match="no WC26 fixture"):
        load_lines(FIXTURES, path, now=NOW)


def test_played_match_is_refused(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Mexico v South Africa,team_total:Mexico,1.5,over,1.91,bet365"],
    )
    with pytest.raises(LineError, match="already played"):
        load_lines(FIXTURES, path, now=NOW)


def test_stale_line_is_refused(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        [
            "2026-06-17T11:00:00,Mexico v South Korea,team_total:Mexico,1.5,over,1.91,bet365",
            "2026-06-17T11:00:00,Mexico v South Korea,team_total:Mexico,1.5,under,1.91,bet365",
        ],
    )
    with pytest.raises(LineError, match="stale"):
        load_lines(FIXTURES, path, now=NOW)  # 25 h old


def test_unknown_team_raises_strict(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Mexica v South Korea,team_total:Mexica,1.5,over,1.91,bet365"],
    )
    with pytest.raises(UnknownTeamError):
        load_lines(FIXTURES, path, now=NOW)


def test_team_not_in_match_is_refused(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Mexico v South Korea,team_total:Brazil,1.5,over,1.91,bet365"],
    )
    with pytest.raises(LineError, match="not in match"):
        load_lines(FIXTURES, path, now=NOW)


def test_one_sided_quote_is_refused(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        ["2026-06-18T10:00:00,Mexico v South Korea,team_total:Mexico,1.5,over,1.91,bet365"],
    )
    with pytest.raises(LineError, match="missing its under"):
        load_lines(FIXTURES, path, now=NOW)


def test_whole_number_line_is_refused(tmp_path: Path) -> None:
    path = write_lines(
        tmp_path,
        [
            "2026-06-18T10:00:00,Mexico v South Korea,team_total:Mexico,2,over,1.91,bet365",
            "2026-06-18T10:00:00,Mexico v South Korea,team_total:Mexico,2,under,1.91,bet365",
        ],
    )
    with pytest.raises(LineError, match="half-integer"):
        load_lines(FIXTURES, path, now=NOW)


def _quote(over_odds: float, under_odds: float) -> TwoWayLine:
    return TwoWayLine(
        ts=NOW,
        match_date=pd.Timestamp("2026-06-18"),
        home_id="mexico",
        away_id="south_korea",
        neutral=False,
        team_id="south_korea",
        market="team_total:south_korea",
        line=1.5,
        over_odds=over_odds,
        under_odds=under_odds,
        book="bet365",
    )


def test_hand_computed_devig_and_edge() -> None:
    """PLAN 4 verification fixture — every number below derived by hand.

    Book quote: over 1.80 / under 2.05.
      implied: 1/1.80 = 0.555556, 1/2.05 = 0.487805, overround = 1.043361
      multiplicative de-vig (D005): fair_over = 0.555556 / 1.043361
                                              = 110/195 * ... = 0.5324675
      (exactly (10/18)/(10/18 + 1/2.05) = 0.5324675324675325)
    Model says P(over) = 0.60:
      edge_over = 0.60 - 0.5324675 = +0.0675325
      ev_over   = 0.60 * 1.80 - 1  = +0.08
      edge_under = 0.40 - 0.4675325 = -0.0675325  -> recommend OVER
    """
    fair_over, fair_under = devig_two_way(1.80, 2.05)
    assert fair_over == pytest.approx(0.5324675324675325, abs=1e-12)
    assert fair_under == pytest.approx(0.4675324675324676, abs=1e-12)
    assert fair_over + fair_under == pytest.approx(1.0)

    edge = evaluate(_quote(1.80, 2.05), model_p_over=0.60)
    assert edge.side == "over"
    assert edge.fair_p == pytest.approx(0.5324675324675325)
    assert edge.edge == pytest.approx(0.60 - 0.5324675324675325)
    assert edge.ev == pytest.approx(0.08)


def test_symmetric_american_quote_devigs_to_half() -> None:
    # -110 both sides: implied 0.523810 each -> fair exactly 0.5/0.5
    dec = 1.0 + 100.0 / 110.0
    fair_over, fair_under = devig_two_way(dec, dec)
    assert fair_over == pytest.approx(0.5)
    assert fair_under == pytest.approx(0.5)
    # model 0.55 -> edge exactly +0.05, the settings.yaml flag threshold
    edge = evaluate(_quote(dec, dec), model_p_over=0.55)
    assert edge.edge == pytest.approx(0.05)
    assert edge.ev == pytest.approx(0.55 * dec - 1.0)


def test_under_side_recommended_and_ranking() -> None:
    low = evaluate(_quote(1.91, 1.91), model_p_over=0.40)  # under edge +0.10
    high = evaluate(_quote(1.80, 2.05), model_p_over=0.70)  # over edge +0.1675
    assert low.side == "under"
    assert low.model_p == pytest.approx(0.60)
    ranked = rank([low, high])
    assert ranked[0] is high


def test_evaluate_rejects_degenerate_model_prob() -> None:
    with pytest.raises(ValueError):
        evaluate(_quote(1.91, 1.91), model_p_over=1.0)
