"""Dated rankings snapshots + diffing (Phase 5.4).

Each `wc26 rankings` run saves the table to
data/processed/rankings/rankings_<YYYY-MM-DD>.parquet (same-day reruns
overwrite — the snapshot reflects the latest state of that match day).
`--diff` compares against the most recent snapshot from an EARLIER date, so
movement between match days is visible.
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from wc26.config import REPO_ROOT
from wc26.sim.mc import RANKINGS_SCHEMA

RANKINGS_DIR = REPO_ROOT / "data" / "processed" / "rankings"
_NAME = re.compile(r"rankings_(\d{4}-\d{2}-\d{2})\.parquet$")


def snapshot_path(date: dt.date) -> Path:
    return RANKINGS_DIR / f"rankings_{date.isoformat()}.parquet"


def save_snapshot(
    frame: pd.DataFrame, date: dt.date, model_version: str, n_runs: int, seed: int
) -> Path:
    out = RANKINGS_SCHEMA.validate(frame).copy()
    out["snapshot_date"] = date.isoformat()
    out["model_version"] = model_version
    out["n_runs"] = n_runs
    out["seed"] = seed
    path = snapshot_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return path


def previous_snapshot(before: dt.date) -> Path | None:
    """Most recent snapshot strictly before `before`, if any."""
    if not RANKINGS_DIR.exists():
        return None
    dated: list[tuple[dt.date, Path]] = []
    for p in RANKINGS_DIR.glob("rankings_*.parquet"):
        m = _NAME.search(p.name)
        if m:
            d = dt.date.fromisoformat(m.group(1))
            if d < before:
                dated.append((d, p))
    return max(dated)[1] if dated else None


def diff_frames(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Per-team movement vs a previous snapshot, ordered by current rank.

    rank_move is positive when the team climbed (previous rank - current).
    """
    cur = RANKINGS_SCHEMA.validate(current)
    prev = RANKINGS_SCHEMA.validate(previous)
    merged = cur.merge(prev, on="team_id", suffixes=("", "_prev"), validate="1:1")
    if len(merged) != len(cur):
        raise ValueError("snapshots cover different team sets — cannot diff")
    merged["rank_move"] = merged["rank_prev"] - merged["rank"]
    for col in ("p_r32", "p_qf", "p_champion", "exp_stage"):
        merged[f"d_{col}"] = merged[col] - merged[f"{col}_prev"]
    cols = [
        "rank",
        "rank_move",
        "team_id",
        "group",
        "p_r32",
        "d_p_r32",
        "p_qf",
        "d_p_qf",
        "p_champion",
        "d_p_champion",
        "exp_stage",
        "d_exp_stage",
    ]
    return merged.sort_values("rank", kind="stable")[cols].reset_index(drop=True)
