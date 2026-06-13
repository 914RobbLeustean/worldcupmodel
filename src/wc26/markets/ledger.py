"""Append-only bet ledger (D006) and CLV accounting.

ledger/bets.csv rules:
- rows are ONLY ever appended (code opens the file in append mode, nothing
  here rewrites); corrections are new rows with the same bet_id — the last
  row per bet_id is the current truth (`latest_view`).
- a bet's life: one `open` row at log time, then one `settled` row carrying
  the manually entered closing quote, the 90-minute result, pnl and CLV.
- ALL bets settle on the 90-minute result (D004): `goals_90` is the bet
  team's goal count after 90 minutes, never the extra-time score.

CLV per bet = odds_taken * fair_closing_p - 1, where fair_closing_p is the
multiplicatively de-vigged (D005) closing probability of the side we bet.
Positive CLV = we beat the close, the success metric of the whole project.
"""

import csv
from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from wc26.config import REPO_ROOT
from wc26.markets.edges import devig_two_way

LEDGER_PATH = REPO_ROOT / "ledger" / "bets.csv"


@dataclass(frozen=True)
class BetRow:
    bet_id: str  # B0001, B0002, ... (same id on the settling/correcting row)
    ts_utc: str  # ISO 8601 seconds, UTC, when this ROW was written
    match: str  # "<home_id> v <away_id>", canonical ids
    match_date: str  # fixture date YYYY-MM-DD
    market: str  # e.g. "team_total:paraguay"
    line: float
    side: str  # over | under
    odds_taken: float  # decimal
    stake: float
    model_prob: float  # model P(side) at log time
    model_version: str
    edge: float  # model_prob - fair_p at log time
    book: str
    status: str  # open | settled
    closing_over_odds: float | None = None
    closing_under_odds: float | None = None
    clv: float | None = None
    goals_90: int | None = None  # bet team's goals after 90' (D004)
    result: str | None = None  # won | lost
    pnl: float | None = None
    note: str | None = None


COLUMNS = [f.name for f in fields(BetRow)]

LEDGER_SCHEMA = pa.DataFrameSchema(
    {
        "bet_id": pa.Column(str, pa.Check.str_matches(r"^B\d{4}$")),
        "ts_utc": pa.Column(str),
        "match": pa.Column(str),
        "match_date": pa.Column(str),
        "market": pa.Column(str),
        "line": pa.Column(float),
        "side": pa.Column(str, pa.Check.isin(["over", "under"])),
        "odds_taken": pa.Column(float, pa.Check.gt(1.0)),
        "stake": pa.Column(float, pa.Check.gt(0.0)),
        "model_prob": pa.Column(float, [pa.Check.gt(0.0), pa.Check.lt(1.0)]),
        "model_version": pa.Column(str),
        "edge": pa.Column(float),
        "book": pa.Column(str, nullable=True),
        "status": pa.Column(str, pa.Check.isin(["open", "settled"])),
        "closing_over_odds": pa.Column(float, pa.Check.gt(1.0), nullable=True),
        "closing_under_odds": pa.Column(float, pa.Check.gt(1.0), nullable=True),
        "clv": pa.Column(float, nullable=True),
        "goals_90": pa.Column(pd.Int64Dtype(), pa.Check.ge(0), nullable=True),
        "result": pa.Column(str, pa.Check.isin(["won", "lost"]), nullable=True),
        "pnl": pa.Column(float, nullable=True),
        "note": pa.Column(str, nullable=True),
    },
    strict=True,
    coerce=True,
)


def _header(path: Path) -> str:
    with path.open() as f:
        return f.readline().strip()


def append_row(row: BetRow, path: Path = LEDGER_PATH) -> None:
    """Append one row. The file is never rewritten (D006)."""
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(",".join(COLUMNS) + "\n")
    elif _header(path) != ",".join(COLUMNS):
        raise ValueError(
            f"{path} header does not match the ledger schema — refusing to append "
            f"(the ledger is append-only; never hand-edit the header)"
        )
    values = [getattr(row, c) for c in COLUMNS]
    with path.open("a", newline="") as f:
        csv.writer(f).writerow(["" if v is None else v for v in values])


def read_ledger(path: Path = LEDGER_PATH) -> pd.DataFrame:
    """Full row history, schema-validated. Empty frame if no bets yet."""
    df = pd.read_csv(path, dtype={"bet_id": str, "note": str, "book": str})
    if list(df.columns) != COLUMNS:
        raise ValueError(f"{path} columns must be {COLUMNS}, got {list(df.columns)}")
    if df.empty:
        return df
    return LEDGER_SCHEMA.validate(df)


def latest_view(history: pd.DataFrame) -> pd.DataFrame:
    """Current truth: the LAST row per bet_id (later rows supersede, D006)."""
    return history.drop_duplicates("bet_id", keep="last").reset_index(drop=True)


def next_bet_id(history: pd.DataFrame) -> str:
    if history.empty:
        return "B0001"
    return f"B{int(history['bet_id'].str.removeprefix('B').astype(int).max()) + 1:04d}"


def open_market_conflicts(history: pd.DataFrame, match: str, market: str) -> pd.DataFrame:
    """OPEN bets already riding the same (match, market) — correlation guard (D029).

    Two lines on one team's total (e.g. O1.5 + O2.5) win and lose together;
    stacking them concentrates bankroll on one event and inflates the
    effective n of the 50-bet CLV gate, which assumes roughly independent
    bets. One open bet per (match, market); a second is refused at log time.
    """
    if history.empty:
        return history
    current = latest_view(history)
    return current[
        (current["status"] == "open") & (current["match"] == match) & (current["market"] == market)
    ].reset_index(drop=True)


@dataclass(frozen=True)
class Settlement:
    result: str  # won | lost
    pnl: float
    clv: float
    fair_closing_p: float


def settle_bet(
    side: str,
    line: float,
    goals_90: int,
    odds_taken: float,
    stake: float,
    closing_over_odds: float,
    closing_under_odds: float,
) -> Settlement:
    """Grade a team-total bet on the 90' score (D004) and compute CLV."""
    if (2 * line) % 2 != 1:
        raise ValueError(f"line must be a half-integer, got {line}")
    if side not in ("over", "under"):
        raise ValueError(f"side must be over/under, got {side!r}")
    won = (goals_90 > line) == (side == "over")
    fair_over, fair_under = devig_two_way(closing_over_odds, closing_under_odds)
    fair_p = fair_over if side == "over" else fair_under
    return Settlement(
        result="won" if won else "lost",
        pnl=stake * (odds_taken - 1.0) if won else -stake,
        clv=odds_taken * fair_p - 1.0,
        fair_closing_p=fair_p,
    )


def clv_report(history: pd.DataFrame) -> pd.DataFrame:
    """Per-market and overall: bets, stake, P&L, ROI, CLV, calibration.

    REAL money and PAPER bets are reported separately (backlog #14): paper
    bets (book == "paper") carry representative notionals that would distort
    the real-money ROI/CLV the project is actually steering by. The per-market
    breakdown and the "TOTAL (real)" row are real money only; paper sits on
    its own clearly-excluded line. The 50-bet CLV/Kelly gate reads the real
    total.

    Calibration here = mean bet-on model probability vs realized win rate;
    with the bet counts this project sees, a bucketed reliability curve would
    be noise (revisit at 50+ settled bets).
    """
    current = latest_view(history)
    settled = current[current["status"] == "settled"].copy()
    if settled.empty:
        return pd.DataFrame()
    settled["market_family"] = settled["market"].str.partition(":")[0]
    settled["won"] = (settled["result"] == "won").astype(float)
    is_paper = settled["book"].fillna("").str.lower() == "paper"
    real = settled[~is_paper]
    paper = settled[is_paper]

    def block(df: pd.DataFrame, label: str) -> dict[str, object]:
        staked = float(df["stake"].sum())
        return {
            "market": label,
            "bets": len(df),
            "staked": staked,
            "pnl": float(df["pnl"].sum()),
            "roi": float(df["pnl"].sum()) / staked,
            "mean_clv": float(df["clv"].mean()),
            "stake_wtd_clv": float((df["clv"] * df["stake"]).sum()) / staked,
            "mean_model_p": float(df["model_prob"].mean()),
            "win_rate": float(df["won"].mean()),
        }

    rows = [block(g, str(family)) for family, g in real.groupby("market_family", sort=True)]
    if not real.empty:
        rows.append(block(real, "TOTAL (real)"))
    if not paper.empty:
        rows.append(block(paper, "paper (excl.)"))
    return pd.DataFrame(rows)
