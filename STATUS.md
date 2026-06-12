# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 5 — DONE (2026-06-12). Phase 4 acceptance still time-gated** on
tonight's USA v Paraguay (kickoff ~02:00 UTC 2026-06-13 in Inglewood — the
match had NOT been played as of this session's end, so settling B0001 now
would mean inventing a result; refused). The simulator & rankings are live.

What exists now (Phase 5, src/wc26/sim/):
- Group-state tracker: official 2026 tiebreakers (art. 13 — h2h FIRST,
  before overall GD, verified in the FIFA regulations PDF; D023), conduct
  from card counts, Elo as the FIFA-ranking proxy; exact per-team
  can/secured/eliminated flags (3^k completion enumeration, D024); MD3
  dead-rubber flags.
- Knockout bracket in git: data/manual/bracket_2026.yaml (matches 73-104,
  R32 slots, dates, venues+countries) + third_place_allocation.csv (FIFA
  Annex C, 495 rows, verified vs both the FIFA PDF and Wikipedia 495/495).
  Loaders re-validate structure on every load. Source notes in docs/DATA.md.
- `wc26 sim` — group standings + statuses + dead rubbers + per-team
  P(win group / top2 / 3rd-qualify / advance) from the seeded MC.
- `wc26 rankings [--diff]` — P(R32→champion) + expected finish for all 48;
  dated snapshot in data/processed/rankings/; --diff vs previous match day.
  Runs in ~6 s (gate <60 s). KO draws → ET/pens mini-match (D024),
  advancement only; futures stay UNBETTABLE (PLAN 5.5).
- Gates as tests (tests/test_sim_gates.py, on constructed fixtures): decided
  outcomes collapse, P(champion) sums to 1, bit-deterministic seed,
  eliminated team → exact 0% after the result lands. Tiebreaker unit tests
  incl. three-way ties (tests/test_standings.py).

## Next task
1. **Finish the Phase 4 acceptance cycle** (carried over, time-gated): after
   USA v Paraguay finishes (~04:00 UTC 2026-06-13): `wc26 data scrape
   --tournament wc2026 && wc26 data sync`, then
   `wc26 settle B0001 --closing-over X --closing-under Y` (real closing
   quotes from the user's book if available; else a representative closing
   quote with --note saying so — the logged line was representative paper
   too) and `wc26 clv-report`. Then tick Phase 4 acceptance here.
2. The user should start entering REAL book lines into data/manual/lines.csv
   (PLAYBOOK §3) — everything downstream is live.
3. Then Phase 6 — tournament ops (docs/PLAN.md): daily routine through the
   group stage; post-group recalibration checkpoint (~2026-07-03) re-gates
   match totals (D019) and corners/cards (D021) and feeds the group-state
   tracker's knockout/stakes context into the cards model.

## Blockers
None. (Phase 4 acceptance is time-gated on tonight's match, not blocked.)

## Daily during tournament (~10 min, see docs/PLAYBOOK.md for the full version)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` →
`wc26 data status` → `uv run wc26 refit` → `uv run wc26 backtest && uv run
pytest` (re-check gates) → `uv run wc26 predict` → settle yesterday's open
bets (closing quotes!) → user enters today's lines → `wc26 edges` →
`wc26 log-bet` each bet taken → `wc26 rankings --diff` (movement snapshot).

## Data inventory (all verified)
- results.parquet: 49,407 played internationals 1872→now + patch layer
- fixtures.parquet: 72 WC26 group matches, venues, altitude, played flags
- bracket_2026.yaml + third_place_allocation.csv: knockout structure
  (manual, in git, FIFA-verified 2026-06-12)
- match_stats.parquet: 675 matches — 211 majors + 462 UEFA WC qualifiers
  (D020, training-only) + WC26 accumulating daily; extra_time flags verified
- market_odds.parquet: 211 historical 1X2 average odds (D015)
- referees.parquet: 122 refs with card rates (2022+ majors, 2025-26 quals)
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked
- Models (data/processed/models/): goal_engine + corners + cards, versioned
  `<name>_<cutoff>_<sha7>.json`; latest fit 2026-06-13 @6fe3a4b (engine
  9,509 matches; props 650). latest-model selection now tie-breaks on
  fitted_at, not filename (D023 note).
- Backtest artifacts: data/processed/backtest/ — all gate tests green
- Rankings snapshots: data/processed/rankings/rankings_2026-06-12.parquet
- Ledger: ledger/bets.csv — 1 open paper bet (B0001, settle next session)

## Last session summary
- 2026-06-12 (e): Phase 5 built & gated — src/wc26/sim/ (standings with the
  OFFICIAL 2026 tiebreakers — h2h first, a deliberate deviation from the
  task brief's 2022-style ordering, verified in the FIFA regulations PDF;
  exact qualification flags; bracket + Annex C data files verified against
  FIFA primary source AND Wikipedia; seeded MC with ET/pens advancement
  layer; rankings + dated snapshots + diff). CLI sim/rankings replace the
  last stubs. D023/D024, DATA.md bracket section, 164 tests green, mypy
  --strict + ruff clean. Daily routine ran clean (0 new results; refit
  @6fe3a4b; gates green; predictions rendered). Phase 4 acceptance NOT
  ticked: USA v Paraguay had not kicked off yet — settling B0001 would have
  required fabricating a result, so it carries to next session.
- 2026-06-12 (d): Phase 4 built — markets layer, ledger, CLV, PLAYBOOK,
  D022; dry-run on the real match day; B0001 logged; results-patch keying
  fix. 136 tests green.
- 2026-06-12 (c): Phase 3 — prop models; team totals ship; match totals +
  corners/cards quarantined (D019/D021).
- 2026-06-12 (b): Phase 2 — goal engine + harness + reality gates.
- 2026-06-12 (a): Phase 1 — ESPN ingest, referee table, sync.

## Phase checklist
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer (teams, results, Elo, match stats, referees)
- [x] Phase 2 — Goal engine + walk-forward backtest harness
- [x] Phase 3 — Prop models (team totals LIVE; corners/cards quarantined D021)
- [x] Phase 4 — Market layer (edges, ledger, CLV) — acceptance: settle B0001
      after tonight's match (next session, step 1 above)
- [x] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration + prop re-gate)
