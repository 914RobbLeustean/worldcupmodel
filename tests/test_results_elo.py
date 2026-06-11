"""Results ingest + Elo on frozen fixtures; full-data tests if ingested."""

from pathlib import Path

import pandas as pd
import pytest

from wc26.config import load_settings
from wc26.data.elo import compute_elo_history, ratings_asof
from wc26.data.results import (
    PROCESSED_DIR,
    RESULTS_SCHEMA,
    build_results,
    tournament_tier,
)

FIXTURE_RAW = Path(__file__).parent / "fixtures" / "results_mini.csv"
FIXTURE_PATCH = Path(__file__).parent / "fixtures" / "patch_mini.csv"


def test_tournament_tiers() -> None:
    assert tournament_tier("FIFA World Cup") == "world_cup"
    assert tournament_tier("FIFA World Cup qualification") == "qualifier"
    assert tournament_tier("UEFA Euro qualification") == "qualifier"
    assert tournament_tier("Copa América") == "continental"
    assert tournament_tier("Friendly") == "friendly"
    assert tournament_tier("FIFI Wild Cup") == "friendly"


def test_build_results_with_patch_override() -> None:
    results, fixtures = build_results(FIXTURE_RAW, FIXTURE_PATCH)
    # patch fills the NA-score WC26 row -> it becomes a played result
    assert len(results) == 4
    patched = results[(results["home_id"] == "mexico") & (results["tier"] == "world_cup")]
    assert len(patched) == 1
    assert patched.iloc[0]["home_score"] == 2
    # fixtures keep both WC26 rows, played flag reflects the patch
    assert len(fixtures) == 2
    assert sorted(fixtures["played"].tolist()) == [False, True]
    assert fixtures[fixtures["city"] == "Mexico City"].iloc[0]["high_altitude"]


def test_elo_basics() -> None:
    results, _ = build_results(FIXTURE_RAW, FIXTURE_PATCH)
    k = load_settings().elo_k
    history = compute_elo_history(RESULTS_SCHEMA.validate(results), k)
    # winner of the only friendly between two fresh teams gains what the loser drops
    asof = ratings_asof(history, "2030-01-01")
    assert pytest.approx(asof.sum(), abs=1e-6) == 1500.0 * asof.size
    # leak-freedom: as-of before any match = empty
    assert ratings_asof(history, "1990-01-01").empty


requires_data = pytest.mark.skipif(
    not (PROCESSED_DIR / "results.parquet").exists(),
    reason="full data not ingested (run `wc26 data ingest`)",
)


@requires_data
def test_full_results_sane() -> None:
    df = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    assert len(df) > 45_000
    assert df["date"].is_monotonic_increasing


@requires_data
def test_full_elo_top_teams() -> None:
    """Sanity vs eloratings.net consensus: elite teams must rank near the top.

    Tolerance (documented per plan): the five perennial elite sides must all
    sit inside our top 12 as of today. Looser than exact-order matching on
    purpose — K-factor details differ from eloratings.net.
    """
    df = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    history = compute_elo_history(RESULTS_SCHEMA.validate(df), load_settings().elo_k)
    top12 = set(ratings_asof(history, "2026-06-11").nlargest(12).index)
    assert {"argentina", "spain", "france", "brazil", "england"} <= top12
