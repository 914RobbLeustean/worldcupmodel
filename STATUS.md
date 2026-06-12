# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 3 — COMPLETE** (2026-06-12). Next: **Phase 4 — Market layer: edges,
ledger, CLV** (docs/PLAN.md).

Phase 3 verdict (full report in docs/MODEL.md, decisions D017–D021):
- **Team totals: LIVE, gates green** — the only model cleared to price
  (count log-loss 1.405 vs naive 1.475; O1.5 calibration slope 0.87).
- **Match totals: QUARANTINED (D019)** — the Phase 2 "under-dispersion" flag
  turned out to be a World-Cup-specific conditional mean miss (engine 2.20
  vs realized 2.66 goals/match at WCs, favorite side); O2.5 slope 0.13.
- **Corners & cards: built, FAILED gates, QUARANTINED (D021)** — lose to the
  naive moment-matched baseline even after extending training with 462 UEFA
  qualifier rows (D020); predictions uncorrelated with outcomes. Re-gate at
  the Phase 6 post-group recalibration. Tests pin all three quarantines.

## Next task
Phase 4 task 1: data/manual/lines.csv format + `wc26 edges` (de-vig two-way
prop lines multiplicatively D005, compare vs model, flag edge ≥ threshold,
flat stake from settings). HARD GUARD: refuse lines for any market that is
not gate-cleared — today that means TEAM TOTALS ONLY (match totals D019,
corners/cards D021, and anything with no prediction). Then `wc26 log-bet` /
`settle` / `clv-report` per PLAN 4.2.

## Blockers
None.

## Daily during tournament (takes ~2 min, do at session start)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` —
pulls finished WC26 matches from ESPN into the patch + processed tables.
Then `wc26 data status` to confirm freshness, `uv run wc26 refit` to fold
new results into all models (engine + corners/cards params, versioned
together), `uv run wc26 predict` for today's matches. Referee assignments
(appear ~2 days out) can be entered in data/manual/ref_assignments.csv
(date,home_id,away_id,referee — ESPN spelling) to switch cards output to
ref-known. (Re-run `wc26 backtest` + `pytest` after refit to re-check all
gates; ~2 min.)

## Data inventory (all verified)
- results.parquet: 49,406 played internationals 1872→now + patch layer
- fixtures.parquet: 72 WC26 group matches, venues, altitude, played flags
- match_stats.parquet: 674 matches — 211 majors (WC18/22, Euro24, Copa24)
  + 462 UEFA WC qualifiers (D020, training-only) + WC26 accumulating daily;
  extra_time flags verified; canceled events skipped (Russia–Poland 2022)
- market_odds.parquet: 211 historical 1X2 average odds (D015)
- referees.parquet: 121 refs with card rates (2022+ majors, 2025-26 quals)
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked
- Models (data/processed/models/): goal_engine + corners + cards, all
  versioned `<name>_<cutoff>_<sha7>.json`; latest fit 2026-06-13 @b3defec
  (engine 9,508 matches; props 649)
- Backtest artifacts: data/processed/backtest/ — goal_engine_* (Phase 2
  gates) + props_* (Phase 3 gates); all gate tests green

## Last session summary
- 2026-06-12 (c): Phase 3 done — team_totals/corners/cards models +
  walk-forward props harness + gates as tests. Quantified the totals flag:
  team totals pass and ship; match totals + corners/cards quarantined with
  pinned tests (D019/D021). Added UEFA WCQ scrape legs (only confederation
  with ESPN team stats, D020), statsmodels dep (D018), ET exclusion for
  props (D017). `predict` prints all prop distributions with uncertainty +
  ref-known/unknown labels in ~1 s; `refit` versions all three models;
  `backtest` runs both harnesses. 99 tests green, mypy --strict clean.
- 2026-06-12 (b): Phase 2 done — goal engine + harness + market odds +
  reality gates; opener ingested. 58 tests green.
- 2026-06-12 (a): Phase 1 finished (ESPN ingest, referee table, sync).

## Phase checklist
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer (teams, results, Elo, match stats, referees)
- [x] Phase 2 — Goal engine + walk-forward backtest harness
- [x] Phase 3 — Prop models (team totals LIVE; corners/cards quarantined D021)
- [ ] Phase 4 — Market layer (edges, ledger, CLV)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration + prop re-gate)
