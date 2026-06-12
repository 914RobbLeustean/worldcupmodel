"""Shared feature engineering for the prop models (corners, cards).

Pure functions, no I/O (CLAUDE.md). Everything here is walk-forward safe by
construction: rate features take an explicit pre-cutoff slice, and stage
features (matchday, knockout) depend only on the match calendar, which is
known before kickoff.

Extra time (D012/D017): corner/card/foul totals in match_stats include extra
time for flagged rows and the 90-minute split is not recoverable from our
sources, so ET rows are EXCLUDED from both training and evaluation of the
90-minute prop models — `props_universe` is the only entry point and it
drops them.
"""

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import yaml

from wc26.config import REPO_ROOT

RIVALRIES_PATH = REPO_ROOT / "config" / "rivalries.yaml"

PROPS_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "tournament": pa.Column(str),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "home_score": pa.Column(int, pa.Check.ge(0)),
        "away_score": pa.Column(int, pa.Check.ge(0)),
        "referee": pa.Column(str, nullable=True),
        "corners_home": pa.Column(float, pa.Check.ge(0)),
        "corners_away": pa.Column(float, pa.Check.ge(0)),
        "yellows_home": pa.Column(float, pa.Check.ge(0)),
        "yellows_away": pa.Column(float, pa.Check.ge(0)),
        "reds_home": pa.Column(float, pa.Check.ge(0)),
        "reds_away": pa.Column(float, pa.Check.ge(0)),
        "fouls_home": pa.Column(float, pa.Check.ge(0)),
        "fouls_away": pa.Column(float, pa.Check.ge(0)),
        "shots_home": pa.Column(float, pa.Check.ge(0)),
        "shots_away": pa.Column(float, pa.Check.ge(0)),
        "matchday": pa.Column(int, pa.Check.ge(1)),
        "knockout": pa.Column(bool),
        "neutral": pa.Column(bool),
        "qualifier": pa.Column(bool),
        "total_corners": pa.Column(int, pa.Check.ge(0)),
        "total_cards": pa.Column(int, pa.Check.ge(0)),
    },
    strict="filter",
    coerce=True,
)


def _attach_neutral(stats: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Join the neutral-venue flag from results by team pair within ±1 day (D013).

    The goal engine's home advantage hinges on this flag, so a miss raises
    (alias or date-drift problem) instead of guessing.
    """
    neutral: list[bool] = []
    for date, home, away in zip(stats["date"], stats["home_id"], stats["away_id"], strict=True):
        window = results[(results["date"] - pd.Timestamp(date)).abs() <= pd.Timedelta(days=1)]
        hit = window[
            ((window["home_id"] == home) & (window["away_id"] == away))
            | ((window["home_id"] == away) & (window["away_id"] == home))
        ]
        if len(hit) != 1:
            raise ValueError(
                f"props row {home} vs {away} on {pd.Timestamp(date).date()}: "
                f"{len(hit)} results matches — check aliases and date drift (D013)"
            )
        neutral.append(bool(hit["neutral"].iloc[0]))
    out = stats.copy()
    out["neutral"] = neutral
    return out


def props_universe(match_stats: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Training/eval universe for 90-minute prop models.

    Drops extra-time rows (D017), requires complete corner/card/foul/shot
    stats (raises if a majors row is missing them — that is ingest drift, not
    something to paper over), attaches the neutral flag from results (the
    engine-derived features need it), and adds stage features:

    - matchday: a team's Nth appearance in that tournament edition; group
      games are 1/2/3, anything later is knockout. Derived purely from the
      match calendar, so it is known pre-kickoff.
    - knockout: both teams past their 3 group games.
    - qualifier: UEFA WC-qualifier rows (D020) — training-only level dummy.
      Their matchday/knockout are forced to the 1/False baseline (appearance
      counting is meaningless across a 2-year campaign; the ~12 playoff
      matches mislabeled as group stage are accepted noise).

    Stat completeness: a finals (majors/WC26) ESPN row with missing stats
    raises — that is ingest drift, not something to paper over. Qualifier
    rows and MANUAL rows (event_id `manual:...`, D027) with missing stats
    are simply dropped: qualifiers because ESPN coverage is best-effort,
    manual rows because an operator's honest "-1 = unknown" entry must not
    wedge the daily refit (the score still flows via results_patch).
    """
    stats = match_stats[~match_stats["extra_time"].astype(bool)].copy()
    is_qualifier = stats["tournament"].str.contains("qualification", case=False)
    is_manual = (
        stats["event_id"].astype(str).str.startswith("manual:")
        if "event_id" in stats.columns
        else pd.Series(False, index=stats.index)
    )
    stat_cols = [
        f"{stat}_{side}"
        for stat in ("corners", "yellows", "reds", "fouls", "shots")
        for side in ("home", "away")
    ]
    incomplete = stats[stat_cols].isna().any(axis=1)
    if (incomplete & ~is_qualifier & ~is_manual).any():
        bad = stats[incomplete & ~is_qualifier & ~is_manual]
        raise ValueError(
            f"{len(bad)} finals match_stats rows are missing prop stats, e.g.\n"
            f"{bad[['date', 'home_id', 'away_id']].head(3)}\n"
            f"— fix ingest (or backfill via `wc26 add-result`), do not train around it"
        )
    stats = stats[~incomplete]

    stats = stats.sort_values(["date", "home_id"], kind="stable").reset_index(drop=True)
    stats = _attach_neutral(stats, results)
    edition = stats["tournament"] + "-" + stats["date"].dt.year.astype(str)
    appearance: dict[tuple[str, str], int] = {}
    matchdays: list[int] = []
    for ed, home, away in zip(edition, stats["home_id"], stats["away_id"], strict=True):
        app_home = appearance.get((ed, home), 0) + 1
        app_away = appearance.get((ed, away), 0) + 1
        appearance[(ed, home)] = app_home
        appearance[(ed, away)] = app_away
        matchdays.append(min(app_home, app_away))
    stats["qualifier"] = stats["tournament"].str.contains("qualification", case=False)
    stats["matchday"] = matchdays
    stats.loc[stats["qualifier"], "matchday"] = 1
    stats["knockout"] = stats["matchday"] >= 4
    stats["total_corners"] = (stats["corners_home"] + stats["corners_away"]).astype(int)
    stats["total_cards"] = (
        stats["yellows_home"] + stats["yellows_away"] + stats["reds_home"] + stats["reds_away"]
    ).astype(int)
    return PROPS_SCHEMA.validate(stats)


def shrunk_team_rates(
    universe: pd.DataFrame, home_col: str, away_col: str, pseudo_matches: float
) -> tuple[dict[str, float], float]:
    """Per-team per-match rate of a stat the team produced, shrunk to the mean.

    A team's appearances on both sides count; shrinkage target is the overall
    per-team-appearance mean. Returns ({team: shrunk rate}, mean) — the mean
    doubles as the fallback for unseen teams.
    """
    per_team = pd.concat(
        [
            pd.Series(universe[home_col].to_numpy(dtype=float), index=universe["home_id"].array),
            pd.Series(universe[away_col].to_numpy(dtype=float), index=universe["away_id"].array),
        ]
    )
    if per_team.empty:
        raise ValueError("cannot compute team rates from an empty universe")
    mean = float(per_team.mean())
    grouped = per_team.groupby(level=0).agg(["sum", "count"])
    shrunk = (grouped["sum"] + pseudo_matches * mean) / (grouped["count"] + pseudo_matches)
    return {str(t): float(r) for t, r in shrunk.items()}, mean


def shrunk_referee_rates(
    universe: pd.DataFrame, pseudo_matches: float
) -> tuple[dict[str, float], float, float]:
    """Referee career total-cards-per-match, shrunk to the all-ref mean.

    Returns ({referee: shrunk rate}, mean, std of the SHRUNK rates). The std
    feeds the ref-unknown variance widening in the cards model: it is the
    spread of the feature values the model actually sees, which is the
    first-order uncertainty an unknown ref's rate carries. (Raw career rates
    would overstate it badly — with 1-5 matches per ref they are mostly
    within-ref noise.) Rows with no referee recorded (all of WC18 — ESPN has
    no officials that far back) contribute nothing; an unknown ref at
    predict time falls back to the mean.
    """
    known = universe[universe["referee"].notna() & (universe["referee"] != "")]
    cards = pd.Series(known["total_cards"].to_numpy(dtype=float), index=known["referee"].array)
    if cards.empty:
        return {}, float(universe["total_cards"].mean()), 0.0
    mean = float(cards.mean())
    grouped = cards.groupby(level=0).agg(["sum", "count"])
    shrunk = (grouped["sum"] + pseudo_matches * mean) / (grouped["count"] + pseudo_matches)
    between_std = float(shrunk.std(ddof=1)) if len(shrunk) > 1 else 0.0
    return {str(r): float(v) for r, v in shrunk.items()}, mean, between_std


def load_rivalries(path: Path = RIVALRIES_PATH) -> frozenset[frozenset[str]]:
    """Order-insensitive rivalry pairs (canonical IDs).

    Not validated against the strict 48-team registry: historical rivals
    (e.g. peru) resolve leniently per D008 and simply never match a WC26 row.
    """
    with path.open() as f:
        raw = yaml.safe_load(f)
    pairs = raw["rivalries"]
    out: set[frozenset[str]] = set()
    for pair in pairs:
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError(f"rivalry entry must be two distinct team IDs, got {pair}")
        out.add(frozenset((str(pair[0]), str(pair[1]))))
    return frozenset(out)


def is_rivalry(home_id: str, away_id: str, rivalries: Iterable[frozenset[str]]) -> bool:
    return frozenset((home_id, away_id)) in rivalries
