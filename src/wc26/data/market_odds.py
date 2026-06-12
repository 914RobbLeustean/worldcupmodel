"""Historical and live 1X2 market odds (the backtest's market baseline).

Sources (verified against each other on overlapping matches, see docs/DATA.md):
- WC 2018 + WC 2022: football-data.co.uk WorldCup2026.xlsx — per-tournament
  sheets with average/max pre-kickoff odds AND the true 90-minute score
  (HGFT/AGFT separate from extra-time/penalty goals).
- Euro 2024 + Copa América 2024: BetExplorer results pages (average odds
  across books). Knockout scores there include extra time; we take only the
  odds and resolve outcomes from our own results + extra_time flags.
- WC 2026 live: BetExplorer fixtures page, snapshotted per day for the
  prediction sanity gate.

All raw downloads are cached forever under data/raw/odds/ — historical
tournaments are immutable, so nothing is ever re-fetched. Odds are AVERAGE
bookmaker odds collected near kickoff, not strictly closing odds; treated as
a closing proxy (documented limitation, docs/DATA.md).
"""

import re
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from wc26.config import REPO_ROOT
from wc26.data.teams import registry

ODDS_RAW = REPO_ROOT / "data" / "raw" / "odds"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

FOOTBALL_DATA_XLSX = ODDS_RAW / "football_data_worldcup.xlsx"
FOOTBALL_DATA_URL = "https://www.football-data.co.uk/WorldCup2026.xlsx"

BETEXPLORER_BASE = "https://www.betexplorer.com"
REQUEST_PAUSE_S = 1.2
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) wc26-edge-model/0.1"

# BetExplorer archives: (cache filename, ajax par=tournament,stage ids, referer path).
# IDs read from each tournament's /results/ page; immutable once final.
BETEXPLORER_ARCHIVES = {
    "euro2024_group": ("1,ABkrguJ9,EcpQtcVi,1", "/football/europe/euro-2024/results/", "UEFA Euro"),
    "euro2024_knockout": (
        "1,ABkrguJ9,SMaVweFA,1",
        "/football/europe/euro-2024/results/",
        "UEFA Euro",
    ),
    "copa2024_group": (
        "1,GIocbJnP,zDzsPsN5,1",
        "/football/south-america/copa-america/results/",
        "Copa América",
    ),
    "copa2024_knockout": (
        "1,GIocbJnP,IyQoO1xC,1",
        "/football/south-america/copa-america/results/",
        "Copa América",
    ),
}
BETEXPLORER_WC26_FIXTURES = "/football/world/world-championship-2026/fixtures/"

MARKET_ODDS_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "tournament": pa.Column(str),
        "home_id": pa.Column(str),
        "away_id": pa.Column(str),
        "odds_home": pa.Column(float, pa.Check.gt(1.0)),
        "odds_draw": pa.Column(float, pa.Check.gt(1.0)),
        "odds_away": pa.Column(float, pa.Check.gt(1.0)),
        "source": pa.Column(str),
    },
    strict="filter",
    coerce=True,
)

# One result row of a BetExplorer table: match link with the two team names,
# then three data-odd cells, then the dd.mm.yyyy date.
_BE_ROW = re.compile(
    r'class="in-match"><span>(?:<strong>)?([^<]+)(?:</strong>)?</span>\s*-\s*'
    r"<span>(?:<strong>)?([^<]+)(?:</strong>)?</span>.*?"
    r'data-odd="([0-9.]+)".*?data-odd="([0-9.]+)".*?data-odd="([0-9.]+)".*?'
    r'class="h-text-right h-text-no-wrap">(\d{2}\.\d{2}\.\d{4})',
    re.S,
)


def _fetch(url: str, referer: str | None = None) -> str:
    headers = {"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body: str = resp.read().decode("utf-8")
    time.sleep(REQUEST_PAUSE_S)
    return body


def _cached_text(cache: Path, url: str, referer: str | None = None) -> str:
    if cache.exists():
        return cache.read_text()
    body = _fetch(url, referer)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(body)
    return body


def parse_betexplorer_results(html: str, tournament: str) -> pd.DataFrame:
    """Parse a BetExplorer results table (static page or AJAX fragment)."""
    reg = registry()
    rows = []
    for home, away, o1, ox, o2, date_str in _BE_ROW.findall(html):
        rows.append(
            {
                "date": pd.to_datetime(date_str, format="%d.%m.%Y"),
                "tournament": tournament,
                "home_id": reg.resolve_lenient(home.strip()),
                "away_id": reg.resolve_lenient(away.strip()),
                "odds_home": float(o1),
                "odds_draw": float(ox),
                "odds_away": float(o2),
                "source": "betexplorer_avg",
            }
        )
    return pd.DataFrame(rows)


def parse_football_data_sheet(xlsx_path: Path, sheet: str, tournament: str) -> pd.DataFrame:
    """One tournament sheet of the football-data.co.uk World Cup workbook."""
    df = pd.read_excel(xlsx_path, sheet_name=sheet)
    reg = registry()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["Date"]),
            "tournament": tournament,
            "home_id": df["Home"].map(reg.resolve_lenient),
            "away_id": df["Away"].map(reg.resolve_lenient),
            "odds_home": df["H-Avg"].astype(float),
            "odds_draw": df["D-Avg"].astype(float),
            "odds_away": df["A-Avg"].astype(float),
            "source": "football_data_avg",
        }
    )
    if out[["odds_home", "odds_draw", "odds_away"]].isna().any().any():
        raise ValueError(f"{sheet}: missing average odds — source format changed?")
    return out


def football_data_90min_results(xlsx_path: Path = FOOTBALL_DATA_XLSX) -> pd.DataFrame:
    """True 90-minute scores for WC18/WC22 (HGFT/AGFT exclude ET and pens).

    Used only by tests to verify our extra-time outcome handling (D012).
    """
    frames = []
    reg = registry()
    for sheet in ("WorldCup2018", "WorldCup2022"):
        df = pd.read_excel(xlsx_path, sheet_name=sheet)
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(df["Date"]),
                    "home_id": df["Home"].map(reg.resolve_lenient),
                    "away_id": df["Away"].map(reg.resolve_lenient),
                    "home_score_90": df["HGFT"].astype(int),
                    "away_score_90": df["AGFT"].astype(int),
                    "finished": df["Finished"].astype(str),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def download_raw() -> list[Path]:
    """Fetch any missing raw odds files (immutable; never re-fetched)."""
    fetched = []
    if not FOOTBALL_DATA_XLSX.exists():
        req = urllib.request.Request(FOOTBALL_DATA_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            FOOTBALL_DATA_XLSX.parent.mkdir(parents=True, exist_ok=True)
            FOOTBALL_DATA_XLSX.write_bytes(resp.read())
        time.sleep(REQUEST_PAUSE_S)
        fetched.append(FOOTBALL_DATA_XLSX)
    for key, (par, referer_path, _) in BETEXPLORER_ARCHIVES.items():
        cache = ODDS_RAW / f"betexplorer_{key}.html"
        if not cache.exists():
            url = f"{BETEXPLORER_BASE}/res/ajax/league-results.php?par={par}&show=all&sort=d"
            _cached_text(cache, url, referer=f"{BETEXPLORER_BASE}{referer_path}")
            fetched.append(cache)
    return fetched


def build_market_odds() -> pd.DataFrame:
    """data/processed/market_odds.parquet — historical 1X2 average odds."""
    download_raw()
    frames = [
        parse_football_data_sheet(FOOTBALL_DATA_XLSX, "WorldCup2018", "FIFA World Cup"),
        parse_football_data_sheet(FOOTBALL_DATA_XLSX, "WorldCup2022", "FIFA World Cup"),
    ]
    for key, (_, _, tournament) in BETEXPLORER_ARCHIVES.items():
        html = (ODDS_RAW / f"betexplorer_{key}.html").read_text()
        df = parse_betexplorer_results(html, tournament)
        if df.empty:
            raise ValueError(f"betexplorer_{key}: no rows parsed — page format changed?")
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
    expected = {"FIFA World Cup": 128, "UEFA Euro": 51, "Copa América": 32}
    counts = out["tournament"].value_counts().to_dict()
    if counts != expected:
        raise ValueError(f"market odds row counts {counts} != expected {expected}")
    validated = MARKET_ODDS_SCHEMA.validate(out)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    validated.to_parquet(PROCESSED_DIR / "market_odds.parquet", index=False)
    return validated


def latest_wc26_snapshot_date() -> str | None:
    """YYYYMMDD of the newest cached live-odds snapshot, or None.

    Lets tests and reports run on the last snapshot without touching the
    network (fetch_wc26_live_odds with this date reads pure cache).
    """
    files = sorted(ODDS_RAW.glob("betexplorer_wc26_fixtures_*.html"))
    return files[-1].stem.rsplit("_", 1)[-1] if files else None


def fetch_wc26_live_odds(snapshot_date: str | None = None) -> pd.DataFrame:
    """Today's BetExplorer average 1X2 odds for upcoming WC26 fixtures.

    Snapshotted once per day under data/raw/odds/; rows have no date column
    on the page, so they join to fixtures by team pair (unique within the
    group stage).
    """
    day = snapshot_date or pd.Timestamp.now(tz="UTC").strftime("%Y%m%d")
    cache = ODDS_RAW / f"betexplorer_wc26_fixtures_{day}.html"
    html = _cached_text(cache, f"{BETEXPLORER_BASE}{BETEXPLORER_WC26_FIXTURES}")
    reg = registry()
    rows = []
    # Fixture rows: match link, then three data-odd cells (no trailing date cell).
    for match in re.finditer(
        r'class="in-match"[^>]*><span>(?:<strong>)?([^<]+?)(?:</strong>)?</span>\s*-\s*'
        r"<span>(?:<strong>)?([^<]+?)(?:</strong>)?</span>(.*?)</tr>",
        html,
        re.S,
    ):
        home, away, rest = match.groups()
        odds = re.findall(r'data-odd="([0-9.]+)"', rest)
        if len(odds) != 3:
            continue
        rows.append(
            {
                "home_id": reg.resolve(home.strip()),
                "away_id": reg.resolve(away.strip()),
                "odds_home": float(odds[0]),
                "odds_draw": float(odds[1]),
                "odds_away": float(odds[2]),
                "source": "betexplorer_avg",
            }
        )
    return pd.DataFrame(rows)
