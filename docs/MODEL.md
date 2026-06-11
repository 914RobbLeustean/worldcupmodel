# Model specifications & results

> Filled in as models land (Phases 2–3). Every fitted model version and every
> backtest report is recorded here. No model is "done" without its backtest
> gates documented.

## Goal engine (Phase 2) — NOT YET BUILT
- Spec: penaltyblog Dixon-Coles, time-decay weighting, tier-weighted training
  (WC > continental > qualifier > friendly), neutral-venue flag, Elo-anchored
  shrinkage for sparse teams. Outputs a full correct-score matrix.
- Gates: beats Elo-only baseline on log-loss; within documented margin of the
  de-vigged closing-odds baseline (beating the market in backtest = suspected
  leak, investigate); live 1X2 within sanity distance of market.

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

## Backtest reports
(none yet)

## Model version log
(none yet)
