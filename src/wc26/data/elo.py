"""Elo ratings computed from the full results history.

World Football Elo Ratings formula (eloratings.net):
- expected = 1 / (1 + 10 ** (-dr / 400)), dr includes +100 for a non-neutral
  home team
- K by tournament tier (config/settings.yaml), scaled by goal-difference
  multiplier: 1 (margin <= 1), 1.5 (margin 2), (11 + margin) / 8 (margin >= 3)

Key property for leak-free backtests: ratings_asof(date) returns each team's
rating using only matches played strictly BEFORE that date.
"""

import pandas as pd

HOME_ADV = 100.0
START_RATING = 1500.0


def compute_elo_history(results: pd.DataFrame, k_by_tier: dict[str, int]) -> pd.DataFrame:
    """One row per (match, team) with the rating BEFORE and AFTER the match.

    `results` must be the validated results table (see results.RESULTS_SCHEMA),
    sorted ascending by date.
    """
    results = results.sort_values("date", kind="stable")
    ratings: dict[str, float] = {}
    rows: list[tuple[pd.Timestamp, str, float, float]] = []

    cols = zip(
        results["date"].tolist(),
        results["home_id"].tolist(),
        results["away_id"].tolist(),
        results["home_score"].tolist(),
        results["away_score"].tolist(),
        results["tier"].tolist(),
        results["neutral"].tolist(),
        strict=True,
    )
    for date, home, away, home_score, away_score, tier, neutral in cols:
        date = pd.Timestamp(date)
        home, away = str(home), str(away)
        hs, aw = int(home_score), int(away_score)
        r_home = ratings.get(home, START_RATING)
        r_away = ratings.get(away, START_RATING)

        dr = r_home - r_away + (0.0 if bool(neutral) else HOME_ADV)
        expected_home = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))

        margin = abs(hs - aw)
        if margin <= 1:
            g = 1.0
        elif margin == 2:
            g = 1.5
        else:
            g = (11.0 + margin) / 8.0

        outcome = 1.0 if hs > aw else 0.0 if hs < aw else 0.5

        k = float(k_by_tier[str(tier)]) * g
        delta = k * (outcome - expected_home)
        ratings[home] = r_home + delta
        ratings[away] = r_away - delta
        rows.append((date, home, r_home, ratings[home]))
        rows.append((date, away, r_away, ratings[away]))

    return pd.DataFrame(rows, columns=["date", "team_id", "rating_before", "rating_after"])


def ratings_asof(history: pd.DataFrame, date: str | pd.Timestamp) -> pd.Series:
    """Rating per team using only matches strictly before `date`."""
    cutoff = pd.Timestamp(date)
    past = history[history["date"] < cutoff]
    latest = past.groupby("team_id")["rating_after"].last()
    latest.name = "rating"
    return latest
