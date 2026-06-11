"""Append-style writers for the hand-entered files in data/manual/.

These files are in git on purpose: every manual data entry is reviewable in
the diff. Team names are strictly resolved before writing — a typo fails here,
not inside a model.
"""

import csv
from pathlib import Path

import pandas as pd

from wc26.config import REPO_ROOT
from wc26.data.results import PATCH_RESULTS
from wc26.data.teams import registry

STATS_PATCH = REPO_ROOT / "data" / "manual" / "stats_patch.csv"
# Column names intentionally match data/processed/match_stats.parquet so the
# overlay in espn._apply_stats_patch needs no translation.
STATS_PATCH_COLUMNS = [
    "date",
    "home_id",
    "away_id",
    "corners_home",
    "corners_away",
    "yellows_home",
    "yellows_away",
    "reds_home",
    "reds_away",
    "referee",
]


def append_result(
    *,
    date: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    corners_home: int = -1,
    corners_away: int = -1,
    yellows_home: int = -1,
    yellows_away: int = -1,
    reds_home: int = -1,
    reds_away: int = -1,
    referee: str = "",
    tournament: str = "FIFA World Cup",
    neutral: bool = True,
) -> list[Path]:
    reg = registry()
    home_id, away_id = reg.resolve(home), reg.resolve(away)
    when = pd.Timestamp(date).date().isoformat()

    written: list[Path] = []
    with PATCH_RESULTS.open("a", newline="") as f:
        csv.writer(f).writerow(
            [
                when,
                reg[home_id].name,
                reg[away_id].name,
                home_score,
                away_score,
                tournament,
                str(neutral).upper(),
            ]
        )
    written.append(PATCH_RESULTS)

    counts = [corners_home, corners_away, yellows_home, yellows_away, reds_home, reds_away]
    has_stats = bool(referee.strip()) or max(counts) >= 0
    if has_stats:
        is_new = not STATS_PATCH.exists()
        with STATS_PATCH.open("a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(STATS_PATCH_COLUMNS)
            writer.writerow([when, home_id, away_id, *counts, referee.strip()])
        written.append(STATS_PATCH)
    return written
