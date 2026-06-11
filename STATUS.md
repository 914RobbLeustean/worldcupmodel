# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 1 — COMPLETE** (2026-06-12). Next: **Phase 2 — Goal engine + walk-forward backtest harness** (docs/PLAN.md).

## Next task
Phase 2 task 1: penaltyblog Dixon-Coles goal engine — time-decay weighting,
tier-weighted training, neutral-venue handling, Elo-anchored shrinkage.
MUST respect D012: exclude/adjust `extra_time` rows when fitting 90' models.
Build alongside the walk-forward harness (Phase 2 task 2); the reality gates
in docs/PLAN.md Phase 2.3 are tests, not judgment calls.

## Blockers
None.

## Daily during tournament (takes ~2 min, do at session start)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` —
pulls finished WC26 matches (score/corners/cards/ref) from ESPN into the
patch + processed tables. Then `wc26 data status` to confirm freshness.

## Data inventory (all verified)
- results.parquet: 49,405 played internationals 1872→now (+patch layer)
- fixtures.parquet: 72 WC26 group matches, venues, altitude, played flags
- match_stats.parquet: 211 major-tournament matches (WC18/22, Euro24,
  Copa24) — corners 100%, cards 100%, refs 100% for 2022+ (none for 2018)
- referees.parquet: 51 refs with card rates
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked

## Phase 1 acceptance notes
- All criteria met except the "≥600 matches with corners+cards" target,
  which assumed FBref qualifiers; superseded by D011 (ESPN majors = 211).
  If Phase 3 prop models need more sample, add fifa.worldq.* legs to
  espn.py TOURNAMENTS (cheap — same parser).
- Known gotchas D012 (extra time) and D013 (UTC date drift) are encoded in
  flags/joins and tested.

## Last session summary
- 2026-06-12: Phase 1 finished. FBref dead (Cloudflare) → built ESPN ingest
  with strict parsers + permanent finished-only caching; scraped 211 majors;
  referee table; `wc26 data scrape|sync`; sync handles UTC drift and
  home/away swaps. 33 tests green, mypy --strict clean. Opener was still in
  play at session end — tomorrow's scrape+sync ingests it.

## Phase checklist
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer (teams, results, Elo, match stats, referees)
- [ ] Phase 2 — Goal engine + walk-forward backtest harness
- [ ] Phase 3 — Prop models (team totals, corners, cards)
- [ ] Phase 4 — Market layer (edges, ledger, CLV)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration)
