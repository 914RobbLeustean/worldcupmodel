"""Load and validate config/settings.yaml.

All money rules and randomness seeds live in settings; code reads them from
here so there is exactly one source of truth.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class GoalEngineSettings:
    tier_weights: dict[str, float]
    training_window_years: int
    elo_anchor_pseudo_matches: float
    elo_anchor_min_effective_matches: float


@dataclass(frozen=True)
class BacktestSettings:
    market_margin: float
    sanity_max_abs_diff: float
    sanity_mean_abs_diff: float
    sanity_favorite_prob: float


@dataclass(frozen=True)
class Settings:
    bankroll: float
    unit_pct: float
    edge_threshold: float
    kelly_enabled: bool
    seed: int
    mc_runs: int
    dixon_coles_decay: float
    elo_k: dict[str, int]
    odds_api_budget: int
    goal_engine: GoalEngineSettings
    backtest: BacktestSettings

    @property
    def unit_stake(self) -> float:
        return self.bankroll * self.unit_pct


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw["kelly_enabled"]:
        # Guard rail: flipping this on requires editing this check too,
        # which forces the CLV > 0 over 50+ bets review (CLAUDE.md invariant).
        raise ValueError("kelly_enabled=true is not supported until CLV criteria are met")
    return Settings(
        bankroll=float(raw["bankroll"]),
        unit_pct=float(raw["unit_pct"]),
        edge_threshold=float(raw["edge_threshold"]),
        kelly_enabled=bool(raw["kelly_enabled"]),
        seed=int(raw["seed"]),
        mc_runs=int(raw["mc_runs"]),
        dixon_coles_decay=float(raw["dixon_coles_decay"]),
        elo_k={k.removeprefix("k_"): int(v) for k, v in raw["elo"].items()},
        odds_api_budget=int(raw["odds_api"]["monthly_credit_budget"]),
        goal_engine=GoalEngineSettings(
            tier_weights={k: float(v) for k, v in raw["goal_engine"]["tier_weights"].items()},
            training_window_years=int(raw["goal_engine"]["training_window_years"]),
            elo_anchor_pseudo_matches=float(raw["goal_engine"]["elo_anchor"]["pseudo_matches"]),
            elo_anchor_min_effective_matches=float(
                raw["goal_engine"]["elo_anchor"]["min_effective_matches"]
            ),
        ),
        backtest=BacktestSettings(
            market_margin=float(raw["backtest"]["market_margin"]),
            sanity_max_abs_diff=float(raw["backtest"]["sanity_max_abs_diff"]),
            sanity_mean_abs_diff=float(raw["backtest"]["sanity_mean_abs_diff"]),
            sanity_favorite_prob=float(raw["backtest"]["sanity_favorite_prob"]),
        ),
    )
