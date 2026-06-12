# Model specifications & results

> Filled in as models land (Phases 2–3). Every fitted model version and every
> backtest report is recorded here. No model is "done" without its backtest
> gates documented.

## Goal engine (Phase 2) — LIVE since 2026-06-12

Implementation: `src/wc26/models/goal_engine.py`; all probability math goes
through penaltyblog 1.11 (DixonColesGoalModel for fitting,
create_dixon_coles_grid for prediction — verified empirically before design,
including that the lambda composition `exp(attack_h + defence_a + ha)` exactly
reproduces the library's own predictions).

### Training data
- results.parquet rows inside a 10-year window before the cutoff (older rows
  carry <1% decay weight anyway; keeps walk-forward refits fast).
- Extra-time rows EXCLUDED via the match_stats `extra_time` flag matched by
  team pair ±1 day; pre-2018 contamination accepted and quantified — D014.
- Per-match fit weight = `exp(-xi * days_before_cutoff) * tier_weight` with
  xi = 0.00126/day (settings `dixon_coles_decay`, half-life ≈ 18 months) and
  tier weights world_cup 3.0 / continental 2.5 / qualifier 2.0 / friendly 1.0
  (mirrors the Elo K ratios; competitive matches are more informative of
  tournament-condition strength, friendlies are rotation-noisy).
- Neutral-venue flag per match: home advantage is learned only from true home
  games and applied only when `neutral=False` (at WC26: host nations only).

### Elo-anchored shrinkage (small-data humility)
After the Dixon-Coles fit, attack and defence are regressed on as-of-cutoff
Elo across all teams with effective sample ≥ 15 weighted matches; every
team's parameters are then blended toward that regression line:

    blended = w * fitted + (1 - w) * (intercept + slope * elo)
    w = n_eff / (n_eff + n0),   n0 = 10 (settings `elo_anchor`)

- n_eff = the team's total fit weight (decay × tier), so "10 pseudo-matches"
  means an Elo prior worth roughly 10 recent competitive matches.
- A team with no trained matches (debutant) is priced purely off its Elo;
  every team in the Elo table gets parameters, so predict never falls back.
- 2026-06-13 fit: anchor slope ≈ +0.0022 attack / −0.0021 defence per Elo
  point (≈ ±0.22 per 100 Elo), home_advantage 0.237, rho −0.051.

### Outputs
Full correct-score grid (16×16) → 1X2, match totals (any line), team totals
(home/away goal distributions). Everything is the 90-minute result (D004).

### Persistence
`wc26 refit` saves JSON to
`data/processed/models/goal_engine_<cutoff>_<sha7>.json` with fit timestamp,
git SHA, data cutoff, n_matches, all hyperparameters, anchor coefficients and
per-team blended strengths. `wc26 predict` prints the version line of the
params file it used. Fits are deterministic (sorted input, no randomness).

## Backtest reports

### 2026-06-12 — Phase 2 walk-forward, 211 matches (WC18, WC22, Euro24, Copa24)

Harness: `src/wc26/backtest/harness.py` (`wc26 backtest` regenerates).
Walk-forward with monthly refit cutoffs (6 fits: Jun/Jul 2018, Nov/Dec 2022,
Jun/Jul 2024); every prediction is from a fit on data strictly before its
cutoff ≤ match date. Eval outcomes are 90-minute outcomes (20 ET matches all
scored as draws — independently verified against football-data's 90' scores).
Baselines: (a) Elo-only — eloratings-formula ratings as of each match with a
draw-width nu refit per cutoff by MLE; (b) de-vigged average market odds
(multiplicative, D005; closing proxy, D015).

| model | log-loss | Brier |
|---|---|---|
| market (de-vigged avg) | **0.9706** | **0.5758** |
| **goal engine** | **0.9952** | **0.5887** |
| Elo-only | 1.0120 | 0.5994 |

Per tournament (log-loss): WC18+WC22 n=128: engine 1.0048, Elo 1.0314,
market 0.9700 · Euro24 n=51: engine 1.0393, Elo 1.0601, market 1.0103 ·
Copa24 n=32: engine 0.8866, Elo 0.8576, market 0.9098. (Copa24 is the one
slice where raw Elo edges the engine — n=32, within noise; the gates assert
on the pooled sample.)

Reality gates (tests/test_gates.py, all green 2026-06-12):
- **Gate i** — engine beats Elo-only on pooled log-loss AND Brier. PASS
  (0.9952 < 1.0120).
- **Gate ii** — engine must NOT beat the market by more than
  `market_margin = 0.01` log-loss; beating the market in backtest = suspected
  leak. PASS (engine is 0.0246 worse — the honest place to be).
- **Gate iii** — live sanity, below.

### Live sanity check (gate iii) — 2026-06-12 snapshot
Model (fit cutoff 2026-06-13) vs de-vigged BetExplorer average odds across
all 71 remaining WC26 group fixtures: mean per-outcome |diff| 0.074, worst
0.211. No strong market favorite (≥0.55) is inverted. Largest deviations,
all "brand vs form" disagreements, model keeps the market's modal outcome:

| match | engine P(home) | market P(home) | max diff |
|---|---|---|---|
| brazil v morocco | 0.37 | 0.58 | 0.21 |
| united_states v australia | 0.34 | 0.54 | 0.20 |
| ecuador v germany | 0.31 | 0.20 | 0.20 |
| australia v turkey | 0.31 | 0.18 | 0.18 |
| united_states v paraguay | 0.32 | 0.50 | 0.17 |

Judgment: the model systematically trusts recent results/Elo more than
squad-value priors (it likes Morocco, Paraguay, Australia, Ecuador more than
the market does). That is the model's actual opinion, not a bug; thresholds
and rationale in D016. Phase 4 CLV tracking adjudicates.

Known limitation: match-totals output looks under-dispersed vs market totals
(e.g. low O2.5 on big-name matches). Only 1X2 is gate-checked in Phase 2;
totals calibration is part of Phase 3 (team-totals prop model) before any
totals bet is priced.

## Prop models (Phase 3) — NOT YET BUILT
- Team totals: marginals of the score matrix.
- Corners: negative-binomial regression (xG gap, attack proxies, stage,
  shrunk team corner rates).
- Cards: negative-binomial (referee career rate, match stakes, rivalry flag,
  knockout flag); ref-unknown predictions are flagged and widened.
- Gates: beat naive tournament-mean baselines on log-loss; calibration slope
  in [0.8, 1.2].

## Tournament simulator (Phase 5) — NOT YET BUILT
- 20k seeded Monte Carlo runs; 2026 format (12 groups, 8 best thirds, R32);
  FIFA tiebreakers; ET/pens resolution rule documented in DECISIONS.md.

## Model version log
- `goal_engine 2026-06-13 @20ae804` — first production fit (2026-06-12),
  9,513 matches (window 2016-06-13 → 2026-06-11, incl. the WC26 opener),
  home_advantage 0.237, rho −0.0508. Backtest: report above.
