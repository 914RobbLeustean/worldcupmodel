"""add-result path: strict team resolution, both patch files written."""

from pathlib import Path

import pytest

from wc26.data import manual
from wc26.data.teams import UnknownTeamError


def test_append_result_writes_both_patches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    results_patch = tmp_path / "results_patch.csv"
    results_patch.write_text("date,home_team,away_team,home_score,away_score,tournament,neutral\n")
    monkeypatch.setattr(manual, "PATCH_RESULTS", results_patch)
    monkeypatch.setattr(manual, "STATS_PATCH", tmp_path / "stats_patch.csv")

    paths = manual.append_result(
        date="2026-06-11",
        home="Mexico",
        away="South Africa",
        home_score=2,
        away_score=1,
        corners_home=7,
        corners_away=3,
        yellows_home=2,
        yellows_away=3,
        reds_home=0,
        reds_away=1,
        referee="Some Ref",
        neutral=False,
    )
    assert len(paths) == 2
    lines = results_patch.read_text().strip().splitlines()
    assert lines[-1] == "2026-06-11,Mexico,South Africa,2,1,FIFA World Cup,FALSE"
    stats_lines = (tmp_path / "stats_patch.csv").read_text().strip().splitlines()
    assert stats_lines[0] == ",".join(manual.STATS_PATCH_COLUMNS)
    assert stats_lines[-1] == "2026-06-11,mexico,south_africa,7,3,2,3,0,1,Some Ref"


def test_append_result_rejects_unknown_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manual, "PATCH_RESULTS", tmp_path / "results_patch.csv")
    with pytest.raises(UnknownTeamError):
        manual.append_result(
            date="2026-06-11", home="Narnia", away="Mexico", home_score=0, away_score=0
        )
