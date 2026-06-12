"""Append-style writers for the hand-entered files in data/manual/.

These files are in git on purpose: every manual data entry is reviewable in
the diff. Team names are strictly resolved before writing — a typo fails here,
not inside a model.

Knockout entries (D027): the score entered is the STORED score — the 120'
total when a match went to extra time, matching both upstream sources
(D012) — with `extra_time=True` so 90' models exclude the row. A level
extra-time score means penalties happened, and the shootout winner is
REQUIRED at entry: the advancing team cannot be reconstructed later.
"""

import csv
from pathlib import Path

import pandas as pd

from wc26.config import REPO_ROOT
from wc26.data.results import PATCH_RESULTS
from wc26.data.teams import registry

STATS_PATCH = REPO_ROOT / "data" / "manual" / "stats_patch.csv"
# Column names intentionally match data/processed/match_stats.parquet so the
# overlay/append in espn._apply_stats_patch needs no translation. Every row
# is self-contained (D027): it can stand in for a whole ESPN row.
STATS_PATCH_COLUMNS = [
    "date",
    "home_id",
    "away_id",
    "tournament",
    "home_score",
    "away_score",
    "extra_time",
    "shootout_winner_id",
    "corners_home",
    "corners_away",
    "yellows_home",
    "yellows_away",
    "reds_home",
    "reds_away",
    "fouls_home",
    "fouls_away",
    "shots_home",
    "shots_away",
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
    fouls_home: int = -1,
    fouls_away: int = -1,
    shots_home: int = -1,
    shots_away: int = -1,
    referee: str = "",
    tournament: str = "FIFA World Cup",
    neutral: bool = True,
    extra_time: bool = False,
    shootout_winner: str = "",
) -> list[Path]:
    reg = registry()
    home_id, away_id = reg.resolve(home), reg.resolve(away)
    when = pd.Timestamp(date).date().isoformat()

    shootout_winner_id = ""
    if shootout_winner.strip():
        if not extra_time:
            raise ValueError(
                "a shootout winner implies extra time — pass extra_time=True "
                "(only knockout matches can have either)"
            )
        if home_score != away_score:
            raise ValueError(
                f"shootout winner given but the score {home_score}-{away_score} is "
                f"decisive — penalties only happen after a level 120' score (D012)"
            )
        shootout_winner_id = reg.resolve(shootout_winner)
        if shootout_winner_id not in (home_id, away_id):
            raise ValueError(
                f"shootout winner {shootout_winner_id!r} is neither {home_id} nor {away_id}"
            )
    elif extra_time and home_score == away_score:
        raise ValueError(
            f"extra time with a level score ({home_score}-{away_score}) means a penalty "
            f"shootout — pass shootout_winner=<team>; the advancing team cannot be "
            f"reconstructed later (D027)"
        )

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

    counts = [
        corners_home,
        corners_away,
        yellows_home,
        yellows_away,
        reds_home,
        reds_away,
        fouls_home,
        fouls_away,
        shots_home,
        shots_away,
    ]
    # The stats row also carries the extra_time flag (D012) and the shootout
    # winner (the simulator's KO-facts path reads it), so a knockout entry
    # must write one even when every count is unknown.
    has_stats = bool(referee.strip()) or max(counts) >= 0 or extra_time
    if has_stats:
        is_new = not STATS_PATCH.exists()
        with STATS_PATCH.open("a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(STATS_PATCH_COLUMNS)
            writer.writerow(
                [
                    when,
                    home_id,
                    away_id,
                    tournament,
                    home_score,
                    away_score,
                    str(extra_time).upper(),
                    shootout_winner_id,
                    *counts,
                    referee.strip(),
                ]
            )
        written.append(STATS_PATCH)
    return written
