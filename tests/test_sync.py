"""WC26 result syncing: UTC date drift, fixture-date canonicalization,
idempotency. All on synthetic parquet files."""

from pathlib import Path

import pandas as pd
import pytest

from wc26.data import sync


@pytest.fixture()
def fake_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    processed = tmp_path / "processed"
    processed.mkdir()
    fixtures = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-11")],
            "home_id": ["mexico"],
            "away_id": ["south_africa"],
            "home_score": pd.array([None], dtype="Int64"),
            "away_score": pd.array([None], dtype="Int64"),
            "city": ["Mexico City"],
            "country": ["Mexico"],
            "neutral": [False],
            "high_altitude": [True],
            "played": [False],
        }
    )
    fixtures.to_parquet(processed / "fixtures.parquet", index=False)
    stats = pd.DataFrame(
        {
            # ESPN date is the next UTC day — must still match the fixture
            "date": [pd.Timestamp("2026-06-12")],
            "tournament": ["FIFA World Cup"],
            "event_id": ["e1"],
            "home_id": ["mexico"],
            "away_id": ["south_africa"],
            "home_score": [2],
            "away_score": [1],
        }
    )
    stats.to_parquet(processed / "match_stats.parquet", index=False)

    patch_csv = tmp_path / "results_patch.csv"
    patch_csv.write_text("date,home_team,away_team,home_score,away_score,tournament,neutral\n")
    monkeypatch.setattr(sync, "PROCESSED_DIR", processed)
    monkeypatch.setattr(sync, "MATCH_STATS_PARQUET", processed / "match_stats.parquet")
    monkeypatch.setattr(sync, "PATCH_RESULTS", patch_csv)
    return patch_csv


def test_sync_appends_with_fixture_date_and_neutral_flag(fake_tables: Path) -> None:
    report = sync.sync_wc26_results()
    assert report.appended == ["2026-06-11 Mexico 2-1 South Africa"]
    line = fake_tables.read_text().strip().splitlines()[-1]
    assert line == "2026-06-11,Mexico,South Africa,2,1,FIFA World Cup,FALSE"


def test_sync_is_idempotent(fake_tables: Path) -> None:
    first = sync.sync_wc26_results()
    second = sync.sync_wc26_results()
    assert len(first.appended) == 1
    assert second.appended == []
    assert second.skipped_already_known == 1
    assert len(fake_tables.read_text().strip().splitlines()) == 2  # header + one row
