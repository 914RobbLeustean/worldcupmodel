# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 2 — COMPLETE** (2026-06-12). Next: **Phase 3 — Prop models: team
totals, corners, cards** (docs/PLAN.md).

## Next task
Phase 3 task 1: team totals — direct marginals of the goal engine's score
matrix (`grid.home_goal_distribution` / `away_goal_distribution`), run
through the existing walk-forward harness (src/wc26/backtest/) for
calibration before pricing any line. Then corners (negative-binomial on
match_stats features), then cards (referee rate is the biggest feature —
referees.parquet is ready). Gates per PLAN 3.4: beat the historical
tournament-mean baseline on log-loss; calibration slope in [0.8, 1.2].
Note from Phase 2: engine match-totals look under-dispersed vs market —
quantify and fix as part of the team-totals work before any totals bet.

## Blockers
None.

## Daily during tournament (takes ~2 min, do at session start)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` —
pulls finished WC26 matches from ESPN into the patch + processed tables.
Then `wc26 data status` to confirm freshness, `uv run wc26 refit` to fold
new results into the model, `uv run wc26 predict` for today's matches.
(Re-run `wc26 backtest` + `pytest` after refit if you want the gates
re-checked against the new fit; takes ~1 min.)

## Data inventory (all verified)
- results.parquet: 49,406 played internationals 1872→now (incl. WC26 opener
  Mexico 2-0 South Africa) + patch layer
- fixtures.parquet: 72 WC26 group matches, venues, altitude, played flags
- match_stats.parquet: 212 matches (211 majors WC18/22, Euro24, Copa24 +
  WC26 accumulating daily) — extra_time flags verified
- market_odds.parquet: 211 historical 1X2 average odds (WC18/22 via
  football-data.co.uk; Euro24/Copa24 via BetExplorer) — cross-verified, D015
- referees.parquet: 51 refs with card rates
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked
- Goal engine: data/processed/models/goal_engine_2026-06-13_20ae804.json
- Backtest artifacts: data/processed/backtest/ (gates read these)

## Phase 2 acceptance notes
- Backtest (211 matches, monthly walk-forward): engine log-loss 0.9952 beats
  Elo-only 1.0120, does not beat market 0.9706 — all three reality gates are
  pytest tests (tests/test_gates.py) and green. Report in docs/MODEL.md.
- `wc26 predict` runs in <1 s from cached data (requirement was <10 s).
- Live sanity (gate iii): mean diff vs market 0.074 over 71 fixtures; the
  big deviations are brand-vs-form opinions, documented in MODEL.md + D016.
- Odds are average-near-kickoff, not strict closing (D015 limitation).

## Last session summary
- 2026-06-12 (b): Phase 2 done — goal engine (Dixon-Coles + decay + tier
  weights + neutral venue + Elo-anchored shrinkage, ET rows excluded D014),
  walk-forward harness with Elo + market baselines, market-odds ingest from
  two cross-verified free sources, reality gates as tests, `wc26
  refit|predict|backtest`. Fixed scrape subset-clobber + empty-day crash.
  58 tests green, mypy --strict clean. Opener ingested and folded into the
  production fit.
- 2026-06-12 (a): Phase 1 finished (ESPN ingest, referee table, sync).

## Phase checklist
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer (teams, results, Elo, match stats, referees)
- [x] Phase 2 — Goal engine + walk-forward backtest harness
- [ ] Phase 3 — Prop models (team totals, corners, cards)
- [ ] Phase 4 — Market layer (edges, ledger, CLV)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration)
