"""Match stats (corners, cards, fouls, shots, referee) from ESPN's JSON API.

Replaces the planned FBref scrape (D011): FBref is behind Cloudflare and its
scraper needs a real Chrome; ESPN serves the same match-level stats as plain
JSON for internationals back to 2018, with the referee in gameInfo.

Caching: every response is stored under data/raw/espn/ and never re-fetched
once the match/day is final. Summaries are only cached when state == "post",
so an in-progress match can never be frozen as a final result.

IMPORTANT (D012): scores and stat totals for knockout matches INCLUDE extra
time. Every row carries `extra_time`; training code that prices 90-minute
markets must handle flagged rows explicitly.
"""

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pandera.pandas as pa

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

ESPN_RAW = REPO_ROOT / "data" / "raw" / "espn"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
STATS_PATCH = REPO_ROOT / "data" / "manual" / "stats_patch.csv"
# event_id prefix of rows born from stats_patch.csv with no ESPN counterpart
# (D027). They are scrubbed and re-derived from the CSV on every build.
MANUAL_EVENT_PREFIX = "manual:"

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
REQUEST_PAUSE_S = 1.2
USER_AGENT = "wc26-edge-model/0.1 (personal research; low volume; cached)"


@dataclass(frozen=True)
class Tournament:
    key: str
    league: str  # ESPN league code
    label: str  # matches `tournament` naming in the results table
    start: date
    end: date


TOURNAMENTS: dict[str, Tournament] = {
    t.key: t
    for t in [
        Tournament("wc2018", "fifa.world", "FIFA World Cup", date(2018, 6, 14), date(2018, 7, 15)),
        Tournament(
            "wc2022", "fifa.world", "FIFA World Cup", date(2022, 11, 20), date(2022, 12, 18)
        ),
        Tournament("euro2024", "uefa.euro", "UEFA Euro", date(2024, 6, 14), date(2024, 7, 14)),
        Tournament(
            "copa2024",
            "conmebol.america",
            "Copa América",
            date(2024, 6, 20),
            date(2024, 7, 15),
        ),
        Tournament("wc2026", "fifa.world", "FIFA World Cup", date(2026, 6, 11), date(2026, 7, 19)),
        # UEFA World Cup qualifiers — the documented Phase 3 escape hatch for
        # corners/cards sample size (D020). UEFA is the ONLY confederation
        # whose qualifiers carry team stats on ESPN (CONMEBOL/AFC/CAF/
        # CONCACAF summaries verified stat-less, 2026-06-12). The 2022 cycle
        # has no officials data (like WC18); 2026 cycle does. Labels match
        # the results CSV so tier mapping ("qualification" -> qualifier) and
        # the ±1-day join (D013) work unchanged.
        Tournament(
            "wcq_uefa_2022",
            "fifa.worldq.uefa",
            "FIFA World Cup qualification",
            date(2021, 3, 24),
            date(2022, 6, 14),
        ),
        Tournament(
            "wcq_uefa_2026",
            "fifa.worldq.uefa",
            "FIFA World Cup qualification",
            date(2025, 3, 20),
            date(2026, 3, 31),
        ),
    ]
}

STAT_FIELDS = {
    "wonCorners": "corners",
    "yellowCards": "yellows",
    "redCards": "reds",
    "foulsCommitted": "fouls",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "possessionPct": "possession",
}

MATCH_STATS_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "tournament": pa.Column(str),
        "event_id": pa.Column(str),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "home_score": pa.Column(int, pa.Check.ge(0)),
        "away_score": pa.Column(int, pa.Check.ge(0)),
        "extra_time": pa.Column(bool),
        # Set ONLY for penalty shootouts: stored scores are the level 120'
        # scores (D012), so the advancing team is unrecoverable from them.
        # The simulator's knockout-facts path needs it (Phase 6.1).
        "shootout_winner_id": pa.Column(str, nullable=True),
        "referee": pa.Column(str, nullable=True),
        **{
            f"{stat}_{side}": pa.Column(pd.Float64Dtype(), nullable=True)
            for stat in STAT_FIELDS.values()
            for side in ("home", "away")
        },
    },
    strict="filter",
    coerce=True,
)


def _fetch(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload: dict[str, Any] = json.loads(resp.read())
    time.sleep(REQUEST_PAUSE_S)
    return payload


# Final-status enums observed on ESPN (verified Nov 2022 WC data). Anything
# unrecognized raises: silently mislabeling extra time corrupts 90' training.
REGULAR_FINAL_STATUSES = {"STATUS_FULL_TIME", "STATUS_FINAL"}
EXTRA_TIME_FINAL_STATUSES = {"STATUS_FINAL_PEN", "STATUS_FINAL_AET", "STATUS_FINAL_ET"}
# ESPN marks these state == "post" too, but no match was played — skip the
# event entirely (seen: Russia v Poland WCQ playoff, canceled March 2022).
NO_MATCH_STATUSES = {"STATUS_CANCELED", "STATUS_POSTPONED", "STATUS_ABANDONED", "STATUS_FORFEIT"}


def _is_extra_time(status: dict[str, Any], event_id: str) -> bool:
    name = str(status.get("name", ""))
    if name in EXTRA_TIME_FINAL_STATUSES:
        return True
    if name in REGULAR_FINAL_STATUSES:
        return False
    detail = str(status.get("detail", ""))
    if detail == "FT":
        return False
    if "Pen" in detail or "AET" in detail:
        return True
    raise ValueError(
        f"event {event_id}: unrecognized final status {name!r} / {detail!r} — "
        f"add it to espn.py status sets after checking whether it implies extra time"
    )


def _is_shootout(status: dict[str, Any]) -> bool:
    return str(status.get("name", "")) == "STATUS_FINAL_PEN" or "Pen" in str(
        status.get("detail", "")
    )


def _day_events(league: str, day: date) -> list[dict[str, Any]]:
    yyyymmdd = day.strftime("%Y%m%d")
    cache = ESPN_RAW / "scoreboard" / f"{league}_{yyyymmdd}.json"
    url = f"{BASE}/{league}/scoreboard?dates={yyyymmdd}"
    if cache.exists():
        with cache.open() as f:
            data: dict[str, Any] = json.load(f)
    else:
        data = _fetch(url)
        events_states = [
            e.get("status", {}).get("type", {}).get("state") for e in data.get("events", [])
        ]
        # Past days with every match final are immutable -> safe to cache.
        if day < date.today() and all(s == "post" for s in events_states):
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
    events: list[dict[str, Any]] = data.get("events", [])
    return events


def _summary(league: str, event_id: str) -> dict[str, Any]:
    cache = ESPN_RAW / "summary" / f"{league}_{event_id}.json"
    url = f"{BASE}/{league}/summary?event={event_id}"
    if cache.exists():
        with cache.open() as f:
            cached: dict[str, Any] = json.load(f)
        return cached
    payload = _fetch(url)
    state = (
        payload.get("header", {})
        .get("competitions", [{}])[0]
        .get("status", {})
        .get("type", {})
        .get("state")
    )
    if state == "post":
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload))
    return payload


def _parse_summary(payload: dict[str, Any], tournament: Tournament) -> dict[str, Any] | None:
    """One flat row per finished match; None if not final."""
    comp = payload["header"]["competitions"][0]
    status = comp.get("status", {}).get("type", {})
    if status.get("state") != "post":
        return None
    if str(status.get("name", "")) in NO_MATCH_STATUSES:
        return None

    event_id = str(comp["id"])
    extra_time = _is_extra_time(status, event_id)

    reg = registry()
    sides: dict[str, dict[str, Any]] = {}
    for competitor in comp["competitors"]:
        side = competitor["homeAway"]
        name = competitor["team"]["displayName"]
        sides[side] = {
            "id": reg.resolve_lenient(name),
            "score": int(competitor["score"]),
            "winner": bool(competitor.get("winner", False)),
        }
    if set(sides) != {"home", "away"}:
        raise ValueError(f"event {event_id}: missing home/away competitors")

    shootout_winner_id: str | None = None
    if _is_shootout(status):
        winners = [s["id"] for s in sides.values() if s["winner"]]
        if len(winners) != 1:
            raise ValueError(
                f"event {event_id}: penalty shootout but ESPN marks {len(winners)} "
                f"winners — the stored level score cannot identify the advancing "
                f"team (D012); fix the source data"
            )
        shootout_winner_id = str(winners[0])

    row: dict[str, Any] = {
        "date": pd.Timestamp(comp["date"]).tz_localize(None).normalize(),
        "tournament": tournament.label,
        "event_id": event_id,
        "home_id": sides["home"]["id"],
        "away_id": sides["away"]["id"],
        "home_score": sides["home"]["score"],
        "away_score": sides["away"]["score"],
        "extra_time": extra_time,
        "shootout_winner_id": shootout_winner_id,
        "referee": None,
        **{f"{stat}_{side}": None for stat in STAT_FIELDS.values() for side in ("home", "away")},
    }

    for team_box in payload.get("boxscore", {}).get("teams", []):
        team_id = reg.resolve_lenient(team_box["team"]["displayName"])
        if team_id == row["home_id"]:
            side = "home"
        elif team_id == row["away_id"]:
            side = "away"
        else:
            raise ValueError(
                f"event {event_id}: boxscore team {team_id!r} matches neither "
                f"{row['home_id']!r} nor {row['away_id']!r} — likely a missing alias "
                f"in config/teams.yaml"
            )
        stats = {s["name"]: s.get("displayValue") for s in team_box.get("statistics", [])}
        for espn_name, ours in STAT_FIELDS.items():
            value = stats.get(espn_name)
            if value is not None and str(value).strip() != "":
                row[f"{ours}_{side}"] = float(str(value).rstrip("%"))

    officials = payload.get("gameInfo", {}).get("officials", [])
    for official in officials:
        position = str(official.get("position", {}).get("displayName") or "")
        if position in ("", "Referee"):
            row["referee"] = official.get("fullName") or official.get("displayName")
            break
    return row


def scrape_tournament(key: str) -> pd.DataFrame:
    """All finished matches of one tournament, from cache where possible."""
    t = TOURNAMENTS[key]
    end = min(t.end, date.today())
    rows: list[dict[str, Any]] = []
    day = t.start
    while day <= end:
        for event in _day_events(t.league, day):
            if event.get("status", {}).get("type", {}).get("state") != "post":
                continue
            row = _parse_summary(_summary(t.league, str(event["id"])), t)
            if row is not None:
                rows.append(row)
        day += timedelta(days=1)
    return pd.DataFrame(rows)


def _patch_value(raw: object) -> str | None:
    """-1 / blank = unknown (no override; NA in a standalone row)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    return None if text in ("", "-1", "-1.0") else text


def _patch_bool(raw: object) -> bool:
    return str(raw).strip().upper() in ("TRUE", "1")


# Per-side columns that swap when a patch row's orientation is flipped vs ESPN.
_SIDE_COLUMNS = [
    ("home_score", "away_score"),
    *((f"{stat}_home", f"{stat}_away") for stat in STAT_FIELDS.values()),
]
_FLIP = {a: b for a, b in _SIDE_COLUMNS} | {b: a for a, b in _SIDE_COLUMNS}


def _apply_stats_patch(df: pd.DataFrame) -> pd.DataFrame:
    """Manual stats entries (data/manual/stats_patch.csv) — override or append.

    D027 contract: a patch row matching an existing row (team pair within
    ±1 day, D013, either orientation — flipped matches flip the per-side
    columns) overrides field-by-field, non-blank values only; more than one
    candidate raises. A row matching nothing becomes a standalone
    match_stats row (event_id `manual:<date>:<home>:<away>`) — the path
    that keeps the tournament loop alive when ESPN never serves a match.
    """
    from wc26.data.manual import STATS_PATCH_COLUMNS

    if not STATS_PATCH.exists():
        return df
    patch = pd.read_csv(STATS_PATCH, dtype=str, keep_default_na=False)
    if patch.empty:
        return df
    if list(patch.columns) != STATS_PATCH_COLUMNS:
        raise ValueError(
            f"{STATS_PATCH} columns must be {STATS_PATCH_COLUMNS} (D027), got "
            f"{list(patch.columns)} — re-enter rows via `wc26 add-result`"
        )
    out = df.reset_index(drop=True)
    new_rows: list[dict[str, Any]] = []
    for entry in patch.to_dict("records"):
        date = pd.Timestamp(str(entry["date"]))
        home, away = str(entry["home_id"]).strip(), str(entry["away_id"]).strip()
        near = (out["date"] - date).abs() <= pd.Timedelta(days=1)
        same = near & (out["home_id"] == home) & (out["away_id"] == away)
        flipped = near & (out["home_id"] == away) & (out["away_id"] == home)
        hits = out[same | flipped]
        if len(hits) > 1:
            raise ValueError(
                f"stats_patch row {home} v {away} on {date.date()} matches "
                f"{len(hits)} match_stats rows — fix the table before patching"
            )
        if len(hits) == 1:
            idx = hits.index[0]
            flip = bool(flipped[idx])
            for col in STATS_PATCH_COLUMNS:
                if col in ("date", "home_id", "away_id", "tournament"):
                    continue
                value = _patch_value(entry[col])
                if value is None:
                    continue  # blank/-1 never erases what ESPN has
                target = _FLIP[col] if flip and col in _FLIP else col
                if col == "extra_time":
                    out.loc[idx, target] = _patch_bool(value)
                elif col in ("home_score", "away_score"):
                    out.loc[idx, target] = int(float(value))
                elif col in ("referee", "shootout_winner_id"):
                    out.loc[idx, target] = value
                else:
                    out.loc[idx, target] = float(value)
        else:
            for col in ("home_score", "away_score"):
                if _patch_value(entry[col]) is None:
                    raise ValueError(
                        f"stats_patch row {home} v {away} on {date.date()} has no ESPN "
                        f"counterpart and no {col} — standalone rows must carry the "
                        f"score (D027); re-enter via `wc26 add-result`"
                    )
            new_rows.append(
                {
                    "date": date,
                    "tournament": str(entry["tournament"]).strip() or "FIFA World Cup",
                    "event_id": f"{MANUAL_EVENT_PREFIX}{date.date()}:{home}:{away}",
                    "home_id": home,
                    "away_id": away,
                    "home_score": int(float(str(entry["home_score"]))),
                    "away_score": int(float(str(entry["away_score"]))),
                    "extra_time": _patch_bool(entry["extra_time"]),
                    "shootout_winner_id": _patch_value(entry["shootout_winner_id"]),
                    "referee": _patch_value(entry["referee"]),
                    **{
                        f"{stat}_{side}": _patch_value(entry[f"{stat}_{side}"])
                        for stat in STAT_FIELDS.values()
                        if stat not in ("shots_on_target", "possession")
                        for side in ("home", "away")
                    },
                }
            )
    if new_rows:
        out = pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)
        out = out.sort_values(["date", "event_id"]).reset_index(drop=True)
    return out


def build_match_stats(keys: list[str] | None = None) -> pd.DataFrame:
    frames = [scrape_tournament(k) for k in (keys or list(TOURNAMENTS))]
    out_path = PROCESSED_DIR / "match_stats.parquet"
    if keys is not None and out_path.exists():
        # Scraping a subset must not drop the tournaments that weren't asked
        # for — keep the existing table underneath the fresh rows. Manual
        # standalone rows are scrubbed: they re-derive from stats_patch.csv
        # below, which lets a later ESPN recovery of the same match convert
        # the entry from standalone row to override without duplication (D027).
        existing = pd.read_parquet(out_path)
        frames.append(existing[~existing["event_id"].str.startswith(MANUAL_EVENT_PREFIX)])
    frames = [f for f in frames if not f.empty]
    if not frames:
        # First day of a tournament before any match has finished.
        return MATCH_STATS_SCHEMA.validate(pd.DataFrame(columns=list(MATCH_STATS_SCHEMA.columns)))
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["date", "event_id"]).drop_duplicates("event_id").reset_index(drop=True)
    df = _apply_stats_patch(df)
    validated = MATCH_STATS_SCHEMA.validate(df)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    validated.to_parquet(PROCESSED_DIR / "match_stats.parquet", index=False)
    return validated


def refresh_match_stats_from_patch() -> pd.DataFrame | None:
    """Re-apply stats_patch.csv to the existing parquet — no network.

    Lets `wc26 add-result` make a manual stats row effective immediately
    (extra_time for settlement, shootout winner for the KO-facts path)
    instead of waiting for the next scrape. None if no parquet exists yet.
    """
    out_path = PROCESSED_DIR / "match_stats.parquet"
    if not out_path.exists():
        return None
    existing = pd.read_parquet(out_path)
    base = existing[~existing["event_id"].str.startswith(MANUAL_EVENT_PREFIX)]
    validated = MATCH_STATS_SCHEMA.validate(_apply_stats_patch(base.reset_index(drop=True)))
    validated.to_parquet(out_path, index=False)
    return validated


def build_referees(match_stats: pd.DataFrame) -> pd.DataFrame:
    """Per-referee card rates from the match stats table (90' + ET as played)."""
    named = match_stats.dropna(subset=["referee"]).copy()
    named["yellows_total"] = named["yellows_home"] + named["yellows_away"]
    named["reds_total"] = named["reds_home"] + named["reds_away"]
    refs = (
        named.groupby("referee")
        .agg(
            matches=("event_id", "count"),
            yellows_per_match=("yellows_total", "mean"),
            reds_per_match=("reds_total", "mean"),
        )
        .reset_index()
        .sort_values("matches", ascending=False)
        .reset_index(drop=True)
    )
    refs.to_parquet(PROCESSED_DIR / "referees.parquet", index=False)
    return refs
