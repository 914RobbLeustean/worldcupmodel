# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 6 — IN PROGRESS. 6.1 (knockout readiness) DONE 2026-06-12; the 6.2
recalibration checkpoint is calendar-gated (~2026-07-03, after the group
stage). Phase 4 acceptance STILL time-gated** on USA v Paraguay (kickoff
~02:00 UTC 2026-06-13 — the match had still not been played as of this
session's end at 16:15 UTC 2026-06-12, so settling B0001 would again mean
inventing a result; refused again).

What exists now (Phase 6.1, on top of the full Phase 0–5 stack):
- KO-facts path: once knockout results land in fixtures.parquet, the
  simulator consumes them as FACTS — sim/tracker.py splits rows on/after
  the bracket's first R32 date (`knockout_facts`), sim/mc.py matches each
  played KO match to its bracket slot by team pair, advances the real
  winner and skips sampling; an unconsumed fact (simulated finishers
  contradicting the real bracket) raises. Pens winners ride
  match_stats.shootout_winner_id from ESPN's winner flag (all 20 historical
  shootouts verified correct).
- `wc26 predict` handles KO fixture rows: knockout=True, no matchday,
  explicit "[KO — 90' probabilities; can draw]" tag. D019/D021 quarantines
  and refusals unchanged.
- Refit cadence: DAILY after every completed match day (D025, PLAYBOOK §1).
- docs/AUDIT.md (2026-06-12): full conformance audit — every PLAN Phase 0–5
  acceptance criterion re-run, all invariants + risk-register rows cited to
  code/tests. 8 findings: 7 now fixed, 1 accepted (pre-commit hook —
  Makefile + session protocol cover it). 192 tests.
- Manual path is knockout-ready (D027, audit finding 8 CLOSED): `wc26
  add-result` captures extra_time, the shootout winner (required when ET
  ends level), and fouls/shots; stats_patch rows are self-contained —
  they override a matching ESPN row (±1 day, flipped orientation handled)
  or become standalone match_stats rows (event_id `manual:...`) when ESPN
  never served the match; add-result refreshes match_stats.parquet
  immediately (no scrape needed); patch-born fixture rows get "unknown"
  venue instead of crashing ingest; incomplete manual rows drop fail-soft
  in props_universe instead of wedging refit. Verified end-to-end in a
  sandbox: manual pens entry → fixtures+stats → knockout_facts resolves
  the advancing team.

## Next task
1. **Finish the Phase 4 acceptance cycle** (carried over twice now,
   time-gated): after USA v Paraguay finishes (~04:00 UTC 2026-06-13):
   `wc26 data scrape --tournament wc2026 && wc26 data sync`, confirm the
   result is in results.parquet, then
   `wc26 settle B0001 --closing-over X --closing-under Y` (real closing
   quotes from the user's book if available; else a representative closing
   quote with --note saying so — the logged line was representative paper
   too) and `wc26 clv-report`. Then tick Phase 4 acceptance here.
2. The user should start entering REAL book lines into data/manual/lines.csv
   (PLAYBOOK §3) — everything downstream is live.
3. **Phase 6.2 recalibration checkpoint — NEXT MILESTONE, ~2026-07-03**
   (after the 72 group matches; do NOT start early): compare predicted vs
   realized over the group stage; re-gate match totals (D019) and
   corners/cards (D021) through the walk-forward harness (a pass needs a
   new DECISIONS entry, never a silent flip); add the knockout flag +
   group-state stakes feature (elimination risk from sim/tracker.py
   TeamStatus) to the cards model; flip the simulator's R32 slots from
   projected to actual (the KO-facts path from 6.1 is the mechanism).

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
  (D020, training-only) + WC26 accumulating daily; extra_time flags verified;
  NEW: shootout_winner_id for pens matches (20 historical, all verified)
- market_odds.parquet: 211 historical 1X2 average odds (D015)
- referees.parquet: 122 refs with card rates (2022+ majors, 2025-26 quals)
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked
- Models (data/processed/models/): goal_engine + corners + cards, versioned
  `<name>_<cutoff>_<sha7>.json`; latest fit 2026-06-13 @508c267 (engine
  9,509 matches; props 650). latest-model selection by (cutoff, fitted_at)
  now pinned by a test (audit finding 2).
- Backtest artifacts: data/processed/backtest/ — all gate tests green
- Rankings snapshots: data/processed/rankings/rankings_2026-06-12.parquet
- Ledger: ledger/bets.csv — 1 open paper bet (B0001, settle next session)

## Last session summary
- 2026-06-12 (g): closed audit finding 8 — the manual data path is
  knockout-ready (D027). add-result: extra_time + shootout-winner +
  fouls/shots capture with hard validation (level ET score REQUIRES the
  winner; winner implies ET + level + in-match); stats_patch.csv rows are
  self-contained and either override an ESPN row (team pair ±1 day, D013,
  flipped orientation flips per-side columns) or append as standalone
  match_stats rows; manual rows scrubbed+re-derived from the CSV every
  build so a later ESPN recovery converts them to overrides without
  duplicates; fixed the latent ingest crash on patch-born fixture rows
  (NaN city → "unknown"); props_universe drops incomplete manual rows
  fail-soft. Sandbox e2e: pens entry → knockout_facts winner resolved.
  12 new tests (192 total), make lint clean. Phase 4 settlement still
  awaits the USA v Paraguay result (next session step 1).
- 2026-06-12 (f): Phase 6.1 + conformance audit. Daily routine clean (0 new
  results — no WC26 match finished between sessions; refit @508c267; gates
  green; predict + rankings rendered). Phase 4 acceptance NOT ticked AGAIN:
  USA v Paraguay still unplayed at 16:15 UTC (kicks off ~02:00 UTC 06-13) —
  settling B0001 would fabricate a result; carries to next session. Built:
  KO-facts path (tracker/mc, ESPN shootout_winner_id), KO-aware predict,
  D025 refit cadence, ET regression tests on constructed WC26 KO rows.
  docs/AUDIT.md: 8 findings — fixed stale MODEL.md Phase 5 section, added
  missing latest_model_path + knockout-draw tests, extracted+tested settle's
  ET refusal, removed unused soccerdata, documented pyarrow (D026); filed
  add-result knockout-readiness (next task 2) and the absent pre-commit
  hook. 180 tests green, mypy --strict + ruff clean, fresh-clone smoke OK.
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
- [ ] Phase 6 — Tournament ops: 6.1 knockout readiness DONE (KO facts, KO
      predict, D025 cadence, audit); 6.2 recalibration checkpoint
      calendar-gated ~2026-07-03 (next task 4)
