# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 4 — BUILT, one acceptance step open** (2026-06-12). The market layer
(edges, ledger, CLV) is implemented, tested (136 tests green, mypy --strict
clean) and dry-run on today's real match day. Definitions in D022; routine in
docs/PLAYBOOK.md.

What exists now:
- `wc26 edges` — de-vigs data/manual/lines.csv (decimal + American parsed at
  the boundary), edge = model_p − fair_p vs the 5% threshold, flat stakes.
  Hard guards (all pinned by tests): TEAM TOTALS ONLY (match totals D019,
  corners/cards D021 refused with decision pointers), no prediction → refuse,
  stale >24 h → refuse, strict team resolution, one-sided quotes → refuse.
- `wc26 log-bet` / `wc26 settle` / `wc26 clv-report` — append-only ledger
  (D006, schema test), 90'-settlement wired explicitly (D004: ET matches
  require --goals because stored scores are 120', D012), CLV = odds_taken ×
  de-vigged closing prob − 1.
- `wc26 odds-check` — optional Odds API h2h sanity check, persisted credit
  counter hard-capped 150/mo (D007); needs ODDS_API_KEY env.

## Next task
1. **Finish the Phase 4 acceptance cycle**: USA v Paraguay finishes ~03:00
   UTC tonight — next session: `wc26 data scrape --tournament wc2026 && wc26
   data sync`, then `wc26 settle B0001 --closing-over X --closing-under Y`
   (closing quote of both sides; the logged line was representative paper —
   the user should ideally supply the real closing numbers from their book)
   and `wc26 clv-report`. Bet B0001: united_states team_total U1.5 @ 1.50,
   paper, stake 15.
2. The user should start entering REAL book lines into data/manual/lines.csv
   (format in PLAYBOOK §3) — everything downstream is live.
3. Then Phase 5 — tournament simulator & rankings (docs/PLAN.md).

## Blockers
None. (Acceptance step 1 is time-gated on tonight's match, not blocked.)

## Daily during tournament (~10 min, see docs/PLAYBOOK.md for the full version)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` →
`wc26 data status` → `uv run wc26 refit` → `uv run wc26 backtest && uv run
pytest` (re-check gates) → `uv run wc26 predict` → settle yesterday's open
bets (closing quotes!) → user enters today's lines → `wc26 edges` →
`wc26 log-bet` each bet taken.

## Data inventory (all verified)
- results.parquet: 49,407 played internationals 1872→now + patch layer
- fixtures.parquet: 72 WC26 group matches, venues, altitude, played flags
- match_stats.parquet: 675 matches — 211 majors (WC18/22, Euro24, Copa24)
  + 462 UEFA WC qualifiers (D020, training-only) + WC26 accumulating daily;
  extra_time flags verified; canceled events skipped (Russia–Poland 2022)
- market_odds.parquet: 211 historical 1X2 average odds (D015)
- referees.parquet: 122 refs with card rates (2022+ majors, 2025-26 quals)
- Elo: leak-free as-of-date snapshots, top-12 sanity-checked
- Models (data/processed/models/): goal_engine + corners + cards, all
  versioned `<name>_<cutoff>_<sha7>.json`; latest fit 2026-06-13 @f355f46
  (engine 9,509 matches; props 650)
- Backtest artifacts: data/processed/backtest/ — goal_engine_* (Phase 2
  gates) + props_* (Phase 3 gates); all gate tests green
- Ledger: ledger/bets.csv — 1 open paper bet (B0001)

## Last session summary
- 2026-06-12 (d): Phase 4 built — src/wc26/markets/ (odds parser, lines.csv
  loader with the gate-clearance/staleness/prediction/strict-team hard
  guards, de-vig+edge math, append-only ledger + CLV). CLI edges/log-bet/
  settle/clv-report + budgeted odds-check. Hand-computed de-vig/edge/CLV
  fixtures per PLAN verification; PLAYBOOK.md finalized; D022. Dry-run on
  the real match day: lines entered, edge report rendered (2 BET flags),
  paper bet B0001 logged; settle guards verified pre-match. Also fixed
  results-patch keying (canonical ids, not spellings — "Czechia" vs "Czech
  Republic" broke ingest after sync; regression test). 136 tests green.
- 2026-06-12 (c): Phase 3 done — team_totals/corners/cards models +
  walk-forward props harness + gates as tests. Team totals pass and ship;
  match totals + corners/cards quarantined with pinned tests (D019/D021).
- 2026-06-12 (b): Phase 2 done — goal engine + harness + market odds +
  reality gates; opener ingested. 58 tests green.
- 2026-06-12 (a): Phase 1 finished (ESPN ingest, referee table, sync).

## Phase checklist
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer (teams, results, Elo, match stats, referees)
- [x] Phase 2 — Goal engine + walk-forward backtest harness
- [x] Phase 3 — Prop models (team totals LIVE; corners/cards quarantined D021)
- [x] Phase 4 — Market layer (edges, ledger, CLV) — acceptance: settle B0001
      after tonight's match (next session, step 1 above)
- [ ] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops (daily routine, recalibration + prop re-gate)
