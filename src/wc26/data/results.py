"""Results + fixtures ingest.

Raw source: martj42 international results CSV (data/raw/results.csv), which
includes WC 2026 fixture rows with NA scores. Live results that the upstream
CSV hasn't picked up yet are layered on from data/manual/results_patch.csv
(patch wins on date+teams).

Outputs (data/processed/):
- results.parquet      every played match, normalized, with tournament tier
- fixtures.parquet     WC 2026 matches (played or not) incl. venue + altitude
"""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

RAW_RESULTS = REPO_ROOT / "data" / "raw" / "results.csv"
PATCH_RESULTS = REPO_ROOT / "data" / "manual" / "results_patch.csv"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# Tournament -> tier. Tier drives Elo K-factors and training weights.
CONTINENTAL = {
    "UEFA Euro",
    "Copa América",
    "African Cup of Nations",
    "AFC Asian Cup",
    "Gold Cup",
    "CONCACAF Championship",
    "Oceania Nations Cup",
    "Confederations Cup",
    "UEFA Nations League",
    "CONCACAF Nations League",
}

# Venues above ~1000 m among WC26 host cities (Estadio Azteca, Guadalajara,
# Monterrey is ~540 m -> not flagged).
HIGH_ALTITUDE_CITIES = {"Mexico City", "Zapopan", "Guadalajara"}

RESULTS_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "home_score": pa.Column(int, pa.Check.ge(0)),
        "away_score": pa.Column(int, pa.Check.ge(0)),
        "tournament": pa.Column(str),
        "tier": pa.Column(
            str, pa.Check.isin(["world_cup", "continental", "qualifier", "friendly"])
        ),
        "neutral": pa.Column(bool),
    },
    strict="filter",
    coerce=True,
)

FIXTURES_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "home_score": pa.Column(pd.Int64Dtype(), nullable=True),
        "away_score": pa.Column(pd.Int64Dtype(), nullable=True),
        "city": pa.Column(str),
        "country": pa.Column(str),
        "neutral": pa.Column(bool),
        "high_altitude": pa.Column(bool),
        "played": pa.Column(bool),
    },
    strict="filter",
    coerce=True,
)


def tournament_tier(tournament: str) -> str:
    if tournament == "FIFA World Cup":
        return "world_cup"
    if "qualification" in tournament.lower():
        return "qualifier"
    if tournament in CONTINENTAL:
        return "continental"
    return "friendly"


def _read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, na_values=["NA"], keep_default_na=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _read_patch(path: Path) -> pd.DataFrame:
    patch = pd.read_csv(path, na_values=["NA"])
    if patch.empty:
        return patch
    patch["date"] = pd.to_datetime(patch["date"])
    return patch


def _apply_patch(raw: pd.DataFrame, patch: pd.DataFrame) -> pd.DataFrame:
    """Patch rows override raw rows with the same (date, home_id, away_id).

    Keys use canonical team ids (lenient resolution), not raw spellings: the
    upstream CSV and the patch may spell the same team differently (e.g.
    "Czech Republic" vs the registry name "Czechia"), and a spelling mismatch
    here would silently duplicate the fixture instead of patching it.
    """
    if patch.empty:
        return raw
    reg = registry()
    cols = ["date", "home_team", "away_team", "home_score", "away_score", "tournament", "neutral"]
    patch = patch.reindex(columns=cols)

    def key_frame(df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            _home_key=df["home_team"].map(reg.resolve_lenient),
            _away_key=df["away_team"].map(reg.resolve_lenient),
        ).set_index(["date", "_home_key", "_away_key"])

    key = ["date", "_home_key", "_away_key"]
    merged = key_frame(raw)
    override = key_frame(patch)
    if not override.index.is_unique:
        dupes = override.index[override.index.duplicated()].tolist()
        raise ValueError(f"results_patch.csv has duplicate match keys: {dupes}")
    merged.update(override[["home_score", "away_score"]])
    new_rows = override.loc[override.index.difference(merged.index)]
    out = pd.concat([merged, new_rows]).reset_index()
    return out.sort_values("date").reset_index(drop=True).drop(columns=key[1:])


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    reg = registry()
    df = df.copy()
    df["home_id"] = df["home_team"].map(reg.resolve_lenient)
    df["away_id"] = df["away_team"].map(reg.resolve_lenient)
    df["tier"] = df["tournament"].map(tournament_tier)
    df["neutral"] = df["neutral"].astype(str).str.upper().isin(["TRUE", "1"])
    return df


def build_results(
    raw_path: Path = RAW_RESULTS, patch_path: Path = PATCH_RESULTS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (results, wc26_fixtures), both schema-validated."""
    raw = _apply_patch(_read_raw(raw_path), _read_patch(patch_path))
    df = _normalize(raw)

    played = (
        df.dropna(subset=["home_score", "away_score"])
        .sort_values("date", kind="stable")
        .reset_index(drop=True)
    )
    played["home_score"] = played["home_score"].astype(int)
    played["away_score"] = played["away_score"].astype(int)
    results = RESULTS_SCHEMA.validate(played)

    wc26 = df[(df["tournament"] == "FIFA World Cup") & (df["date"] >= "2026-01-01")].copy()
    # Strict resolution: every WC26 participant must be in the registry.
    for col in ("home_team", "away_team"):
        wc26[col].map(registry().resolve)
    wc26["high_altitude"] = wc26["city"].isin(HIGH_ALTITUDE_CITIES)
    wc26["played"] = wc26["home_score"].notna() & wc26["away_score"].notna()
    wc26["home_score"] = wc26["home_score"].astype(pd.Int64Dtype())
    wc26["away_score"] = wc26["away_score"].astype(pd.Int64Dtype())
    fixtures = FIXTURES_SCHEMA.validate(wc26.reset_index(drop=True))
    return results, fixtures


def write_processed(results: pd.DataFrame, fixtures: pd.DataFrame) -> dict[str, Path]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "results": PROCESSED_DIR / "results.parquet",
        "fixtures": PROCESSED_DIR / "fixtures.parquet",
    }
    results.to_parquet(paths["results"], index=False)
    fixtures.to_parquet(paths["fixtures"], index=False)
    return paths


def ingest() -> dict[str, Path]:
    results, fixtures = build_results()
    return write_processed(results, fixtures)


def freshness() -> dict[str, str]:
    """Human-readable status per processed table (for `wc26 data status`)."""
    builders = {
        "results": "wc26 data ingest",
        "fixtures": "wc26 data ingest",
        "match_stats": "wc26 data scrape",
        "referees": "wc26 data scrape",
    }
    status: dict[str, str] = {}
    for name, builder in builders.items():
        path = PROCESSED_DIR / f"{name}.parquet"
        if not path.exists():
            status[name] = f"MISSING — run `{builder}`"
            continue
        df = pd.read_parquet(path)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date()
        detail = (
            f"latest match {pd.Timestamp(df['date'].max()).date()}, "
            if "date" in df.columns
            else ""
        )
        status[name] = f"{len(df)} rows, {detail}built {mtime}"
    return status
