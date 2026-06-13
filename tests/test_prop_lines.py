"""Historical prop-line ingest + eval tests (backlog #3/#8, D036).

Pure-function tests run anywhere. Ingest tests need the processed
market_odds/results parquets; verdict tests need the eval artifact (produced
by `uv run wc26 eval-prop-lines`). Both skip on a fresh clone, per convention.
"""

import json

import pytest

from wc26.backtest.prop_lines import (
    NINETY_MIN_TOTAL,
    PROP_LINES_SUMMARY_JSON,
    _devig_over,
    attach_realized,
)
from wc26.data.historical_prop_lines import (
    parse_source,
)
from wc26.data.results import PROCESSED_DIR

# ---------------------------------------------------------------- pure functions


def test_devig_over_two_way_round_trip() -> None:
    # a fair 50/50 with 5% vig each side -> de-vigged back to ~0.5
    p = _devig_over(1.90, 1.90)
    assert abs(p - 0.5) < 1e-9
    # a lopsided line: over heavily favored
    assert _devig_over(1.04, 14.5) > 0.9
    # de-vigged over + under == 1 by construction
    assert abs(_devig_over(2.10, 1.75) + _devig_over(1.75, 2.10) - 1.0) < 1e-9


def test_parse_source_handles_wording_and_separators() -> None:
    text = "\n".join(
        [
            "Eur24",
            "GROUP STAGE:",
            "Portugal - Czech Republic:",  # ' - ' separator
            "1/X/2 = 1.36/4.75/10.00",
            "Total O/U +2.5 - 2.10/1.83",
            "",
            "WorldCup2022",
            "GROUP STAGES:",
            "South Korea Portugal:",  # no separator (split-fix)
            "1/X/2 = 1.22/6.50/15.00",
            "Total Over/Under +2.5 - 2.32/1.72",  # alternate wording
            "PLAYOFFS:",
            "England vs Senegal:",  # ' vs ' separator
            "1/X/2 = 1.65/3.70/6.50",
            "Total O/U +2.5 - 2.5/1.75",
        ]
    )
    matches = parse_source(text)
    assert [m["teams"] for m in matches] == [
        ["Portugal", "Czech Republic"],
        ["South Korea", "Portugal"],
        ["England", "Senegal"],
    ]
    assert [m["tournament"] for m in matches] == ["UEFA Euro", "FIFA World Cup", "FIFA World Cup"]
    assert [m["stage"] for m in matches] == ["group", "group", "knockout"]
    assert matches[0]["totals"][2.5] == (2.10, 1.83)


def test_ninety_minute_patch_values() -> None:
    # 90' totals for the 4 ET matches whose ET-inclusive score differs (D012):
    assert NINETY_MIN_TOTAL[("FIFA World Cup", frozenset({"argentina", "france"}))] == 4  # 2-2@90
    assert NINETY_MIN_TOTAL[("FIFA World Cup", frozenset({"croatia", "brazil"}))] == 0  # 0-0@90
    assert NINETY_MIN_TOTAL[("UEFA Euro", frozenset({"spain", "germany"}))] == 2  # 1-1@90
    assert NINETY_MIN_TOTAL[("UEFA Euro", frozenset({"england", "slovakia"}))] == 2  # 1-1@90
    assert len(NINETY_MIN_TOTAL) == 10


# ------------------------------------------------------------------ ingest (data)

needs_market_odds = pytest.mark.skipif(
    not (PROCESSED_DIR / "market_odds.parquet").exists(),
    reason="market_odds.parquet missing — run `uv run wc26 backtest`",
)


@pytest.fixture(scope="module")
def built():  # type: ignore[no-untyped-def]
    from wc26.data.historical_prop_lines import build_historical_prop_lines

    return build_historical_prop_lines(write=False)


@needs_market_odds
def test_build_recovers_every_match(built) -> None:  # type: ignore[no-untyped-def]
    matches = built[["tournament", "date", "home_team", "away_team"]].drop_duplicates()
    assert len(matches) == 115
    assert matches.groupby("tournament").size().to_dict() == {"FIFA World Cup": 64, "UEFA Euro": 51}
    assert len(built) == 688  # full O/U ladder minus 2 dropped malformed tail lines


@needs_market_odds
def test_croatia_morocco_rematch_is_split(built) -> None:  # type: ignore[no-untyped-def]
    cm = built[
        built.home_team.isin(["croatia", "morocco"])
        & built.away_team.isin(["croatia", "morocco"])
        & (built.line == 2.5)
    ]
    assert len(cm) == 2  # group + 3rd-place, two distinct dates
    assert sorted(cm["date"].dt.strftime("%Y-%m-%d")) == ["2022-11-23", "2022-12-17"]


@needs_market_odds
def test_france_poland_in_both_tournaments(built) -> None:  # type: ignore[no-untyped-def]
    fp = built[
        built.home_team.isin(["france", "poland"])
        & built.away_team.isin(["france", "poland"])
        & (built.line == 2.5)
    ]
    by_t = dict(zip(fp["tournament"], fp["date"].dt.year, strict=True))
    assert by_t == {"FIFA World Cup": 2022, "UEFA Euro": 2024}


@needs_market_odds
def test_decimal_typo_corrections_applied(built) -> None:  # type: ignore[no-untyped-def]
    aa = built[
        (built.home_team == "argentina") & (built.away_team == "australia") & (built.line == 5.5)
    ]
    assert float(aa.iloc[0]["over_odds"]) == 14.00  # source had 1.400
    # dropped malformed lines are absent
    sr = built[
        (built.line == 5.5) & (built.home_team == "slovakia") & (built.away_team == "romania")
    ]
    assert len(sr) == 0


# --------------------------------------------------------------- realized (data)

needs_processed = pytest.mark.skipif(
    not all(
        (PROCESSED_DIR / f).exists()
        for f in ("market_odds.parquet", "results.parquet", "match_stats.parquet")
    ),
    reason="processed parquets missing",
)


@needs_processed
def test_attach_realized_uses_ninety_minute_total(built) -> None:  # type: ignore[no-untyped-def]
    import pandas as pd

    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    df = attach_realized(built, results, stats)
    # spain v germany: ET-inclusive 2-1 (total 3) but 90' is 1-1 (total 2) ->
    # at line 2.5 that flips over to UNDER. The patch must win.
    sg = df[(df.home_team == "spain") & (df.away_team == "germany") & (df.line == 2.5)].iloc[0]
    assert sg["total_goals_90"] == 2
    assert bool(sg["extra_time"]) is True


# ----------------------------------------------------------------- verdict (json)

needs_summary = pytest.mark.skipif(
    not PROP_LINES_SUMMARY_JSON.exists(),
    reason="prop-lines summary missing — run `uv run wc26 eval-prop-lines`",
)


@pytest.fixture(scope="module")
def summary():  # type: ignore[no-untyped-def]
    with PROP_LINES_SUMMARY_JSON.open() as f:
        return json.load(f)


@needs_summary
def test_summary_covers_the_full_sample(summary) -> None:  # type: ignore[no-untyped-def]
    assert summary["n_matches"] == 115
    assert summary["n_lines"] == 688
    assert summary["rho_headline"] == 0.0


@needs_summary
def test_consensus_match_total_close_is_near_unpredictable(summary) -> None:  # type: ignore[no-untyped-def]
    """The #3 verdict, vindicating the D019/D028 match-total quarantine with an
    independent market price: the consensus O2.5 close barely beats the base
    rate and barely separates outcomes (corr ~0.09). If a data refresh ever
    shows the match-total close is actually sharp, this fails and forces a
    re-think of the quarantine."""
    cal = summary["close_calibration"]["2.5"]
    assert cal["n"] == 115
    assert abs(cal["log_loss_skill_vs_naive"]) < 0.01  # close ~ naive at the central line
    assert cal["corr_with_outcome"] < 0.20  # near-zero discrimination


@needs_summary
def test_anchoring_reproduces_the_independent_close(summary) -> None:  # type: ignore[no-untyped-def]
    """D028 validated against a real total price for the first time: the
    1X2-anchored grid reproduces the independent totals close (high corr, equal
    log-loss). If this breaks, the anchoring premise needs revisiting."""
    anc = summary["anchoring"]
    assert anc["corr_p_over"] > 0.85
    assert abs(anc["anchored_log_loss"] - anc["close_log_loss"]) < 0.005


@needs_summary
def test_edge_threshold_floor_is_above_the_phase0_guess(summary) -> None:  # type: ignore[no-untyped-def]
    """#8: the Phase-0 0.05 sits below the median market disagreement (~0.064),
    so it flags normal disagreement, not book error. The data supports a higher
    floor; the team-total threshold is finalized forward from live CLV."""
    q = summary["edge_threshold"]["abs_edge_quantiles"]
    assert 0.04 < q["0.5"] < 0.09
    assert q["0.75"] > 0.05  # 0.05 is below the 75th-pct disagreement
