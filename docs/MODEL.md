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

## Prop models (Phase 3) — built 2026-06-12

All three run through the walk-forward props harness
(`src/wc26/backtest/props.py`, artifacts under data/processed/backtest/,
gates in tests/test_prop_gates.py). Eval universe: the 211 majors minus the
20 extra-time rows (D017 — prop stat totals include ET and the 90' split is
unrecoverable, so ET matches can be neither trained on nor scored), i.e. 191
matches with true 90-minute counts. Naive baselines, walk-forward at every
cutoff: Poisson at the pre-cutoff majors scoring mean (totals);
moment-matched NB2 — mean AND dispersion — on pre-cutoff majors
(corners/cards). Calibration slope = logistic recalibration of the over
outcome on logit(p) at the canonical line nearest each stat's mean.

### Team totals (src/wc26/models/team_totals.py) — LIVE, gates green
Direct marginals of the goal-engine score grid; the model version IS the
engine version. Walk-forward over 191 matches:

| metric | engine | naive | gate |
|---|---|---|---|
| per-side count log-loss | **1.4050** | 1.4750 | beat naive: PASS |
| team O1.5 binary log-loss (n=382 sides) | **0.6053** | 0.6504 | — |
| team O1.5 calibration slope | **0.869** | — | in [0.8, 1.2]: PASS |

### Match totals — QUARANTINED, do not price (D019)
The Phase 2 "under-dispersion vs market" flag, quantified against outcomes:
- Match-totals count log-loss 1.8728 LOSES to naive 1.8520; O2.5 binary
  log-loss 0.7182 vs naive 0.6923; pooled O2.5 calibration slope **0.13**
  (within tournament: WC 0.28, Euro24 0.17, Copa24 −0.18).
- Re-diagnosis: it is NOT grid variance. Empirical home/away goal covariance
  is −0.14 (the grid's ≈ 0), and the variance-ratio "under-dispersion"
  (residual var / mean predicted var = 1.19) is driven by conditional MEAN
  errors: the engine under-predicts World Cup scoring specifically
  (predicted 2.20 vs realized 2.66 goals/match over WC18+WC22 n=118;
  Euro24 2.47 vs 2.37 and Copa24 2.34 vs 2.26 are fine), concentrated on
  the favorite's side (listed-home pred 1.24 vs realized 1.45) —
  Elo-anchored shrinkage compresses mismatch lambdas, and World Cups have
  the most mismatches.
- Team totals survive this (ranking intact, slope in range, big naive
  margin); the SUM's signal does not. `wc26 predict` prints match O/U with
  an explicit "NOT validated" tag; Phase 4 edges must refuse match-total
  lines; test_match_totals_remain_quarantined pins the failure so it cannot
  silently rot. Engine mean recalibration belongs to the Phase 6
  recalibration checkpoint (it would move the 1X2 gates too).

### Corners (src/wc26/models/corners.py) — QUARANTINED, do not price (D021)
NB2 regression (statsmodels, D018) on: engine xG gap + favorite probability
(fit at the same walk-forward cutoff), shrunk team shots/corners rates
(leave-one-out in training so a match never sees its own stats), MD3 +
knockout dummies, qualifier level dummy (D020).

Walk-forward, 141 finals matches (eval starts at the 2018-07 cutoff; 462
UEFA qualifier rows in training from 2021 on):

| metric | model | naive (moment-matched NB2) | gate |
|---|---|---|---|
| count log-loss | 2.7189 | **2.7107** | beat naive: **FAIL** |
| O9.5 binary log-loss | 0.6985 | **0.6871** | — |
| O9.5 calibration slope | **−0.72** | — | in [0.8, 1.2]: **FAIL** |

Predicted means are uncorrelated with outcomes (pooled r = −0.12; WC22
−0.21, Euro24 +0.13, Copa24 +0.02) while the level is right (pred 9.09 vs
realized 9.23). The same pipeline recovers planted signal on synthetic data
(tests/test_negbin.py, tests/test_corners_cards.py), so this is a no-signal
verdict, not a bug.

### Cards (src/wc26/models/cards.py) — QUARANTINED, do not price (D021)
NB2 on: shrunk referee career total-cards rate (the lead feature; LOO in
training), knockout, rivalry (config/rivalries.yaml, only fit when ≥
min_flag_support training rows), shrunk team fouls rates, qualifier dummy.
Target = yellows + reds, each counting 1 (the standard total-cards market —
bookings-points markets are a different contract and are not priced).
Referee unknown OR known-but-historyless → mean rate, variance widened by
the ref-coefficient times the between-ref spread of shrunk rates
(alpha_eff = alpha + (beta_ref·sigma_ref)²), output flagged ref_known=False.

Walk-forward, 141 finals matches (70 ref-known / 71 ref-unknown):

| metric | model | naive (moment-matched NB2) | gate |
|---|---|---|---|
| count log-loss | 2.2236 | **2.1524** | beat naive: **FAIL** |
| O3.5 binary log-loss | 0.7561 | **0.7071** | — |
| O3.5 calibration slope | **−0.18** | — | in [0.8, 1.2]: **FAIL** |

Predicted means uncorrelated with outcomes (pooled r = −0.07; even the
ref-known slice is −0.16 — WC22-era referee careers are ≤7 matches and
shrink to the mean). Tournament-level shocks dominate both stats: Euro24 ran
hot (realized 9.96 corners, 4.26 cards vs ~9.2/~3.6 history) and no
per-match feature can see that coming.

### Phase 3 verdict
Team totals is the ONLY model cleared to price. Corners/cards (and match
totals) are quarantined: `wc26 predict` prints them as reference with
explicit tags, Phase 4 `wc26 edges` must refuse their lines, and
tests/test_prop_gates.py pins the failures. Re-gate at the Phase 6
post-group recalibration (~70 WC26 matches + referee careers grown by WC26
assignments + 2025-26 qualifier officials). Rationale and the no-fishing
call: D019/D021.

## Market-anchor experiment (2026-06-12) — D028, pivot adopted

Question (from the strategic review, docs/BACKLOG.md #1/#2): does the
de-vigged market 1X2 price team totals better than the engine's own grid?
Implementation: `src/wc26/models/market_anchor.py` (solve DC lambdas that
reproduce a de-vigged 1X2; rho=0 headline — zero fitted parameters, zero
leak risk) + `src/wc26/backtest/market_anchor.py` (runs inside
`wc26 backtest`, artifacts in data/processed/backtest/, verdict pinned by
tests/test_market_anchor.py). Identical 191 eval rows and metrics as the
Phase 3 totals backtest; odds joined from market_odds.parquet (D015 —
near-kickoff averages, so live use carries a small optimism bias).

| metric (191 matches) | anchored | engine | naive |
|---|---|---|---|
| team count log-loss | **1.3897** | 1.4051 | 1.4750 |
| team O1.5 binary log-loss (n=382) | **0.5971** | 0.6053 | — |
| team O1.5 calibration slope | **0.864** | 0.869 | — |

rho sensitivity: −0.05 gives 1.3850 (second-order). 1X2 blend weight over
the 211-match Phase 2 sample: **w\* = 0.00** — the optimal engine/market mix
puts zero weight on the engine, i.e. raw `model_p − fair_p` edges are noise.
Match totals: anchored count-LL 1.8452 beats naive 1.8520 (engine 1.8729)
but O2.5 slope 0.458 — still QUARANTINED, D019 unchanged (pre-registered).

Verdict: live team-total pricing moves to market-anchored grids (the book's
1X2 supplies the level, the grid the shape; edge = the book's prop line vs
its own 1X2). Betting on raw engine edges is PAUSED until the wiring lands
(D028). The engine keeps the simulator, corners/cards features, gate iii,
and quote-less prediction (a refuse-to-bet condition, not a fallback).

## Tournament simulator (Phase 5) — LIVE since 2026-06-12
- 20k seeded Monte Carlo runs (~6 s); 2026 format: 12 groups, top 2 + 8 best
  thirds via FIFA Annex C (495-row allocation table in git), R32 → final.
- Official 2026 tiebreakers (art. 13, h2h FIRST — D023); conduct and FIFA-
  ranking proxies documented in D023. ET/pens advancement rule: D024.
- Knockout facts (Phase 6.1): played KO matches enter as facts matched to
  bracket slots by team pair; pens winners come from ESPN's winner flag
  (match_stats.shootout_winner_id). Nothing here is bettable (PLAN 5.5);
  gates in tests/test_sim_gates.py + tests/test_ko_facts.py.

## Model version log
- `goal_engine 2026-06-13 @20ae804` — first production fit (2026-06-12),
  9,513 matches (window 2016-06-13 → 2026-06-11, incl. the WC26 opener),
  home_advantage 0.237, rho −0.0508. Backtest: report above.
