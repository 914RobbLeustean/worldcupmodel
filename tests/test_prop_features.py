"""Prop feature engineering on constructed fixtures: stage derivation,
ET exclusion (D017), qualifier handling (D020), shrinkage arithmetic."""

import pandas as pd
import pytest

from wc26.models.prop_features import (
    is_rivalry,
    load_rivalries,
    props_universe,
    shrunk_referee_rates,
    shrunk_team_rates,
)

STAT_COLS = [
    f"{stat}_{side}"
    for stat in ("corners", "yellows", "reds", "fouls", "shots")
    for side in ("home", "away")
]


def _stats_row(
    date: str,
    home: str,
    away: str,
    tournament: str = "FIFA World Cup",
    extra_time: bool = False,
    referee: str | None = None,
    **overrides: float | None,
) -> dict:
    row = {
        "date": pd.Timestamp(date),
        "tournament": tournament,
        "home_id": home,
        "away_id": away,
        "home_score": 1,
        "away_score": 0,
        "extra_time": extra_time,
        "referee": referee,
        **{c: 4.0 for c in STAT_COLS},
    }
    row.update(overrides)
    return row


def _results_for(stats: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": stats["date"],
            "home_id": stats["home_id"],
            "away_id": stats["away_id"],
            "neutral": True,
        }
    )


def _mini_tournament() -> pd.DataFrame:
    # 4 teams, full group round-robin over MD1-3, then a "final" (4th game).
    rows = [
        _stats_row("2030-06-01", "aa", "bb"),
        _stats_row("2030-06-01", "cc", "dd"),
        _stats_row("2030-06-05", "aa", "cc"),
        _stats_row("2030-06-05", "bb", "dd"),
        _stats_row("2030-06-09", "aa", "dd"),
        _stats_row("2030-06-09", "bb", "cc"),
        _stats_row("2030-06-14", "aa", "bb"),  # knockout: both at appearance 4
    ]
    return pd.DataFrame(rows)


def test_stage_derivation() -> None:
    stats = _mini_tournament()
    uni = props_universe(stats, _results_for(stats))
    assert uni["matchday"].tolist() == [1, 1, 2, 2, 3, 3, 4]
    assert uni["knockout"].tolist() == [False] * 6 + [True]
    assert not uni["qualifier"].any()


def test_extra_time_rows_are_excluded() -> None:
    stats = _mini_tournament()
    stats.loc[6, "extra_time"] = True
    uni = props_universe(stats, _results_for(stats))
    assert len(uni) == 6
    assert not uni["knockout"].any()


def test_majors_with_missing_stats_raise() -> None:
    stats = _mini_tournament()
    stats.loc[2, "corners_home"] = None
    with pytest.raises(ValueError, match="missing prop stats"):
        props_universe(stats, _results_for(stats))


def test_incomplete_qualifier_rows_are_dropped_not_fatal() -> None:
    stats = _mini_tournament()
    extra = pd.DataFrame(
        [
            _stats_row("2030-03-01", "aa", "cc", tournament="FIFA World Cup qualification"),
            _stats_row(
                "2030-03-05",
                "bb",
                "dd",
                tournament="FIFA World Cup qualification",
                corners_home=None,
            ),
        ]
    )
    stats = pd.concat([stats, extra], ignore_index=True)
    uni = props_universe(stats, _results_for(stats))
    assert len(uni) == 8  # 7 finals + 1 complete qualifier
    quals = uni[uni["qualifier"]]
    assert len(quals) == 1
    assert quals["matchday"].tolist() == [1]
    assert not quals["knockout"].any()


def test_unmatched_results_row_raises() -> None:
    stats = _mini_tournament()
    results = _results_for(stats).iloc[1:]
    with pytest.raises(ValueError, match="results matches"):
        props_universe(stats, results)


def test_totals_columns() -> None:
    stats = _mini_tournament()
    stats.loc[0, "corners_home"] = 7.0
    stats.loc[0, "corners_away"] = 3.0
    stats.loc[0, "yellows_home"] = 2.0
    stats.loc[0, "yellows_away"] = 1.0
    stats.loc[0, "reds_home"] = 1.0
    stats.loc[0, "reds_away"] = 0.0
    uni = props_universe(stats, _results_for(stats))
    assert uni.loc[0, "total_corners"] == 10
    assert uni.loc[0, "total_cards"] == 4


def test_shrunk_team_rates_hand_computed() -> None:
    stats = pd.DataFrame(
        [
            _stats_row("2030-06-01", "aa", "bb", corners_home=8.0, corners_away=2.0),
            _stats_row("2030-06-05", "aa", "bb", corners_home=10.0, corners_away=4.0),
        ]
    )
    uni = props_universe(stats, _results_for(stats))
    rates, mean = shrunk_team_rates(uni, "corners_home", "corners_away", pseudo_matches=2.0)
    assert mean == pytest.approx(6.0)  # (8+2+10+4)/4
    assert rates["aa"] == pytest.approx((18 + 2 * 6.0) / 4)  # (8+10 + n0*mean)/(2+n0)
    assert rates["bb"] == pytest.approx((6 + 2 * 6.0) / 4)


def test_shrunk_referee_rates() -> None:
    stats = pd.DataFrame(
        [
            _stats_row("2030-06-01", "aa", "bb", referee="Ref A", yellows_home=3.0),
            _stats_row("2030-06-05", "cc", "dd", referee="Ref A", yellows_home=5.0),
            _stats_row("2030-06-09", "aa", "cc", referee=None),
        ]
    )
    uni = props_universe(stats, _results_for(stats))
    # total_cards: RefA games = 3+4+0+4=11? -> computed from the row stats:
    cards_a = uni[uni["referee"] == "Ref A"]["total_cards"].tolist()
    rates, mean, std = shrunk_referee_rates(uni, pseudo_matches=1.0)
    assert mean == pytest.approx(sum(cards_a) / 2)
    assert rates["Ref A"] == pytest.approx((sum(cards_a) + 1 * mean) / 3)
    assert std == 0.0  # single ref -> no between-ref spread


def test_no_referees_at_all() -> None:
    stats = _mini_tournament()
    uni = props_universe(stats, _results_for(stats))
    rates, mean, std = shrunk_referee_rates(uni, pseudo_matches=8.0)
    assert rates == {}
    assert mean == pytest.approx(uni["total_cards"].mean())
    assert std == 0.0


def test_rivalries_load_and_are_order_insensitive() -> None:
    rivalries = load_rivalries()
    assert is_rivalry("mexico", "united_states", rivalries)
    assert is_rivalry("united_states", "mexico", rivalries)
    assert not is_rivalry("mexico", "canada", rivalries)
