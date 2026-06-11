"""Sync finished WC26 matches from ESPN match stats into results_patch.csv.

Bridges the two sources with their known mismatches handled explicitly:
- dates: ESPN uses UTC kickoff dates, fixtures use local dates -> match on
  team pair within ±1 day (D013), and always write the FIXTURE's date so the
  results table keeps one canonical date per match.
- home/away order: must agree between sources; a swapped pair is matched but
  reported, an unmatched or ambiguous pair raises.
- neutral flag: taken from the fixtures table (host-nation home games are
  non-neutral), never guessed.

Idempotent: matches already played in the results table or already present in
the patch are skipped.
"""

import csv
from dataclasses import dataclass

import pandas as pd

from wc26.config import REPO_ROOT
from wc26.data.results import PATCH_RESULTS, PROCESSED_DIR
from wc26.data.teams import registry

MATCH_STATS_PARQUET = REPO_ROOT / "data" / "processed" / "match_stats.parquet"


@dataclass(frozen=True)
class SyncReport:
    appended: list[str]
    skipped_already_known: int
    swapped_home_away: list[str]


def sync_wc26_results() -> SyncReport:
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    stats = pd.read_parquet(MATCH_STATS_PARQUET)
    wc26 = stats[
        (stats["tournament"] == "FIFA World Cup") & (stats["date"] >= pd.Timestamp("2026-06-01"))
    ]

    patch_keys: set[tuple[str, str, str]] = set()
    if PATCH_RESULTS.exists():
        existing = pd.read_csv(PATCH_RESULTS)
        reg = registry()
        for row in existing.itertuples(index=False):
            patch_keys.add(
                (
                    str(pd.Timestamp(str(row.date)).date()),
                    reg.resolve(str(row.home_team)),
                    reg.resolve(str(row.away_team)),
                )
            )

    reg = registry()
    appended: list[str] = []
    swapped: list[str] = []
    skipped = 0

    stat_rows = zip(
        wc26["date"].tolist(),
        wc26["home_id"].tolist(),
        wc26["away_id"].tolist(),
        wc26["home_score"].tolist(),
        wc26["away_score"].tolist(),
        strict=True,
    )
    for raw_date, raw_home, raw_away, raw_home_score, raw_away_score in stat_rows:
        home_id, away_id = str(raw_home), str(raw_away)
        espn_date = pd.Timestamp(raw_date)

        window = fixtures[abs(fixtures["date"] - espn_date) <= pd.Timedelta(days=1)]
        exact = window[(window["home_id"] == home_id) & (window["away_id"] == away_id)]
        if exact.empty:
            flipped = window[(window["home_id"] == away_id) & (window["away_id"] == home_id)]
            if flipped.empty:
                raise ValueError(
                    f"ESPN match {home_id} vs {away_id} on {espn_date.date()} has no "
                    f"fixture within ±1 day — check team aliases and fixtures table"
                )
            if len(flipped) > 1:
                raise ValueError(f"ambiguous fixture match for {home_id} vs {away_id}")
            fixture = flipped.iloc[0]
            home_id, away_id = away_id, home_id
            home_score, away_score = int(raw_away_score), int(raw_home_score)
            swapped.append(f"{home_id} vs {away_id}")
        else:
            if len(exact) > 1:
                raise ValueError(f"ambiguous fixture match for {home_id} vs {away_id}")
            fixture = exact.iloc[0]
            home_score, away_score = int(raw_home_score), int(raw_away_score)

        if bool(fixture["played"]):
            skipped += 1
            continue
        fixture_date = str(pd.Timestamp(fixture["date"]).date())
        key = (fixture_date, home_id, away_id)
        if key in patch_keys:
            skipped += 1
            continue

        with PATCH_RESULTS.open("a", newline="") as f:
            csv.writer(f).writerow(
                [
                    fixture_date,
                    reg[home_id].name,
                    reg[away_id].name,
                    home_score,
                    away_score,
                    "FIFA World Cup",
                    str(bool(fixture["neutral"])).upper(),
                ]
            )
        patch_keys.add(key)
        appended.append(
            f"{fixture_date} {reg[home_id].name} {home_score}-{away_score} {reg[away_id].name}"
        )

    return SyncReport(appended, skipped, swapped)
