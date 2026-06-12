"""Rankings snapshot persistence + diffing (Phase 5.4)."""

import datetime as dt

import pandas as pd
import pytest

from wc26.sim import snapshots


def _frame(p_champion: list[float], ranks: list[int]) -> pd.DataFrame:
    n = len(p_champion)
    return pd.DataFrame(
        {
            "team_id": [f"t{i}" for i in range(n)],
            "group": ["A"] * n,
            "p_group_win": [0.5] * n,
            "p_r32": [0.9] * n,
            "p_r16": [0.5] * n,
            "p_qf": [0.3] * n,
            "p_sf": [0.2] * n,
            "p_final": [0.1] * n,
            "p_champion": p_champion,
            "exp_stage": [1.5] * n,
            "rank": ranks,
        }
    )


def test_save_and_previous_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setattr(snapshots, "RANKINGS_DIR", tmp_path)
    frame = _frame([0.1, 0.2], [2, 1])
    p1 = snapshots.save_snapshot(frame, dt.date(2026, 6, 11), "test v1", 100, 1)
    p2 = snapshots.save_snapshot(frame, dt.date(2026, 6, 12), "test v1", 100, 1)
    assert p1.exists() and p2.exists()
    saved = pd.read_parquet(p2)
    assert set(saved["snapshot_date"]) == {"2026-06-12"}
    assert set(saved["model_version"]) == {"test v1"}
    # diff target: the latest snapshot strictly before the given date
    assert snapshots.previous_snapshot(dt.date(2026, 6, 12)) == p1
    assert snapshots.previous_snapshot(dt.date(2026, 6, 13)) == p2
    assert snapshots.previous_snapshot(dt.date(2026, 6, 11)) is None


def test_diff_frames_movement() -> None:
    prev = _frame([0.10, 0.20], [2, 1])
    cur = _frame([0.25, 0.15], [1, 2])
    moves = snapshots.diff_frames(cur, prev)
    t0 = moves[moves["team_id"] == "t0"].iloc[0]
    assert t0["rank_move"] == 1  # climbed from 2 to 1
    assert t0["d_p_champion"] == pytest.approx(0.15)
    t1 = moves[moves["team_id"] == "t1"].iloc[0]
    assert t1["rank_move"] == -1
    assert list(moves["rank"]) == [1, 2]  # ordered by current rank


def test_diff_rejects_mismatched_team_sets() -> None:
    prev = _frame([0.1, 0.2], [2, 1])
    cur = _frame([0.1, 0.2], [2, 1]).assign(team_id=["t0", "OTHER"])
    with pytest.raises(ValueError, match=r"different team sets|not unique|columns"):
        snapshots.diff_frames(cur, prev)
