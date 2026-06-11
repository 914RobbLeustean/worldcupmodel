# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 0 — Scaffold** (in progress)

## Next task
Finish Phase 0 acceptance: `uv sync && make test` green from fresh clone, `wc26 --help` lists stub commands, all docs exist. Then start Phase 1, task 1 (team registry — see plan in DECISIONS.md D000 / docs/PLAN.md).

## Blockers
None.

## Last session summary
- 2026-06-11: Repo created, uv project (py3.12), deps pinned (penaltyblog 1.11, pandas 3, pandera, soccerdata, typer). Docs system written. CLI stubs + smoke tests added.

## Phase checklist
- [ ] Phase 0 — Scaffold
- [ ] Phase 1 — Data layer (teams, results, Elo, FBref stats, schedule)
- [ ] Phase 2 — Goal engine + walk-forward backtest harness
- [ ] Phase 3 — Prop models (team totals, corners, cards)
- [ ] Phase 4 — Market layer (edges, ledger, CLV)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration)
