"""add-result path: strict team resolution, both patch files written,
knockout entry validation (extra time / shootout winner, D027)."""

from pathlib import Path

import pytest

from wc26.data import manual
from wc26.data.teams import UnknownTeamError


@pytest.fixture
def patched_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    results_patch = tmp_path / "results_patch.csv"
    results_patch.write_text("date,home_team,away_team,home_score,away_score,tournament,neutral\n")
    monkeypatch.setattr(manual, "PATCH_RESULTS", results_patch)
    monkeypatch.setattr(manual, "STATS_PATCH", tmp_path / "stats_patch.csv")
    return tmp_path


def test_append_result_writes_both_patches(patched_paths: Path) -> None:
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
        fouls_home=12,
        fouls_away=15,
        shots_home=14,
        shots_away=6,
        referee="Some Ref",
        neutral=False,
    )
    assert len(paths) == 2
    lines = (patched_paths / "results_patch.csv").read_text().strip().splitlines()
    assert lines[-1] == "2026-06-11,Mexico,South Africa,2,1,FIFA World Cup,FALSE"
    stats_lines = (patched_paths / "stats_patch.csv").read_text().strip().splitlines()
    assert stats_lines[0] == ",".join(manual.STATS_PATCH_COLUMNS)
    assert stats_lines[-1] == (
        "2026-06-11,mexico,south_africa,FIFA World Cup,2,1,FALSE,,7,3,2,3,0,1,12,15,14,6,Some Ref"
    )


def test_append_result_rejects_unknown_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manual, "PATCH_RESULTS", tmp_path / "results_patch.csv")
    with pytest.raises(UnknownTeamError):
        manual.append_result(
            date="2026-06-11", home="Narnia", away="Mexico", home_score=0, away_score=0
        )


def test_pens_entry_writes_extra_time_and_winner(patched_paths: Path) -> None:
    """A knockout pens result: level stored score + flag + advancing team."""
    paths = manual.append_result(
        date="2026-06-29",
        home="Argentina",
        away="Mexico",
        home_score=1,
        away_score=1,
        extra_time=True,
        shootout_winner="Argentina",
    )
    assert len(paths) == 2  # the stats row is written even with no counts
    stats_lines = (patched_paths / "stats_patch.csv").read_text().strip().splitlines()
    assert stats_lines[-1] == (
        "2026-06-29,argentina,mexico,FIFA World Cup,1,1,TRUE,argentina,"
        "-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,"
    )


def test_level_extra_time_without_shootout_winner_refused(patched_paths: Path) -> None:
    with pytest.raises(ValueError, match="shootout"):
        manual.append_result(
            date="2026-06-29",
            home="Argentina",
            away="Mexico",
            home_score=1,
            away_score=1,
            extra_time=True,
        )


def test_shootout_winner_without_extra_time_refused(patched_paths: Path) -> None:
    with pytest.raises(ValueError, match="extra time"):
        manual.append_result(
            date="2026-06-29",
            home="Argentina",
            away="Mexico",
            home_score=1,
            away_score=1,
            shootout_winner="Argentina",
        )


def test_shootout_winner_with_decisive_score_refused(patched_paths: Path) -> None:
    with pytest.raises(ValueError, match="decisive"):
        manual.append_result(
            date="2026-06-29",
            home="Argentina",
            away="Mexico",
            home_score=2,
            away_score=1,
            extra_time=True,
            shootout_winner="Argentina",
        )


def test_shootout_winner_must_be_in_match(patched_paths: Path) -> None:
    with pytest.raises(ValueError, match="neither"):
        manual.append_result(
            date="2026-06-29",
            home="Argentina",
            away="Mexico",
            home_score=1,
            away_score=1,
            extra_time=True,
            shootout_winner="France",
        )
