# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 1 — Data layer** (~70% done)

## Next task
FBref match-stats ingest (Phase 1 item 4): scrape corners/cards/fouls/shots +
referee for WC 2018, WC 2022, Euro 2024, Copa 2024, qualifiers 2023→2026 via
soccerdata's cached FBref interface (~1 req/6s — expect a long, resumable run;
cache permanently under data/raw/). Then build config/referees.yaml + ref
card-rate table → data/processed/match_stats.parquet (target ≥600 matches with
corners+cards). After that: Phase 2 (goal engine + backtest harness).

## Blockers
None. Note: today's opener (Mexico–South Africa) won't be in the upstream CSV
immediately — enter it tomorrow via `wc26 add-result`.

## Done so far (Phase 1)
- Team registry: 48 teams/12 groups verified vs final draw (Wikipedia + FIFA),
  alias resolution (accent/case-insensitive), strict vs lenient modes (D008).
- Results ingest: 49,405 played internationals (1872→2026-06-10) + all 72 WC26
  group fixtures with venues/altitude flags, pandera-validated parquet;
  manual patch layer overrides upstream lag.
- Elo: full-history ratings, as-of-date snapshots (leak-free), eloratings-style
  formula with tier K-factors; top-12 sanity-checked (Spain #1, Argentina #2).
- `wc26 add-result` (writes results_patch + stats_patch, strict team check,
  auto re-ingest), `wc26 data ingest|status|elo`.

## Last session summary
- 2026-06-11: Phase 0 complete (scaffold, docs, CLI, guard-rail tests) and
  Phase 1 ~70%: registry, results+fixtures ingest, Elo, manual-entry path.
  25 tests green, mypy --strict clean.

## Phase checklist
- [x] Phase 0 — Scaffold
- [ ] Phase 1 — Data layer (remaining: FBref match stats + referee table)
- [ ] Phase 2 — Goal engine + walk-forward backtest harness
- [ ] Phase 3 — Prop models (team totals, corners, cards)
- [ ] Phase 4 — Market layer (edges, ledger, CLV)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration)
