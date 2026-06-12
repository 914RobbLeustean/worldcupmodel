# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Newest entries on top.
Every working session must add at least one entry under `[Unreleased]`.

## [Unreleased]

### Added
- 2026-06-12: Phase 5 — tournament simulator & country rankings
  (src/wc26/sim/). (1) Group-state tracker: standings under the OFFICIAL
  2026 tiebreakers (art. 13 verified in the FIFA regulations PDF — h2h
  among tied teams comes FIRST, unlike 2018/2022; conduct from card counts;
  FIFA-ranking criterion proxied by as-of Elo; D023), per-team
  can/secured/eliminated flags from exact 3^k completion enumeration, and
  MD3 dead-rubber detection (D024). (2) Knockout bracket entered once in
  data/manual/bracket_2026.yaml + third_place_allocation.csv (FIFA Annex C,
  all 495 combinations, parsed from the regulations PDF and verified
  495/495 against Wikipedia's transcription; loaders re-validate on every
  load; docs/DATA.md). (3) `wc26 sim`: seeded Monte Carlo (mc_runs=20000)
  of all remaining matches from the goal-engine score grid; played matches
  are fact; knockout 90' draws resolve via the explicit ET/pens mini-match
  (Poisson at 1/3 rate, then a fair coin — advancement only, D004/D024);
  host home advantage in knockouts when playing in-country. (4)
  `wc26 rankings [--diff]`: P(R32..champion) + expected finish for all 48,
  dated snapshots in data/processed/rankings/, movement vs the previous
  match day. (5) Simulator gates AS TESTS on constructed fixtures: decided
  outcomes collapse to certainty, P(champion) sums to exactly 1,
  bit-deterministic under the settings seed, eliminated team -> exact 0%
  everywhere after the result lands; plus tiebreaker unit tests incl.
  three-way ties and FIFA-pinned bracket/allocation rows. 28 new tests
  (164 total). Runtime: `wc26 rankings` ~6 s end to end (<60 s gate).

### Fixed
- 2026-06-12: latest_*_path() (engine/corners/cards) now picks the newest
  model by (data_cutoff, fitted_at) from the payload instead of a filename
  sort that tie-broke same-cutoff refits on the git SHA (D023 note).
- 2026-06-12: retired the Phase 5 CLI stubs + their smoke test (`wc26 sim`
  and `wc26 rankings` are real commands now).

### Added
- 2026-06-12: Phase 4 — market layer (src/wc26/markets/): manual line entry
  + edges + append-only ledger + CLV. (1) data/manual/lines.csv format
  finalized (one row per quoted side; decimal AND signed-American odds
  parsed at the boundary, stored decimal-only) and `wc26 edges`:
  multiplicative de-vig of two-way quotes via penaltyblog (D005), edge =
  model_p − fair_p vs the 5% threshold, flat-stake recommendation, table
  sorted by edge. HARD GUARDS as tests: only gate-cleared markets priceable
  (team totals ONLY today; match totals D019 and corners/cards D021 refused
  with their decision ids), matches without a prediction refused, stale
  quotes (>24 h) refused, strict team resolution, one-sided quotes refused.
  (2) Ledger: bets.csv schema finalized pre-first-bet (D022); `wc26 log-bet`
  appends open rows (edge recomputed through the same de-vig as edges),
  `wc26 settle` grades on the 90' score (D004 — auto-read from results only
  when no extra_time flag, else --goals mandatory since stored ET scores are
  120', D012) + manually entered closing two-way quote → CLV = odds_taken ×
  fair_closing_p − 1; `wc26 clv-report` prints CLV/ROI/win-rate-vs-model_p
  by market. Append-only enforced by construction + tests (settled rows are
  new rows; re-settling blocked). (3) Hand-computed de-vig/edge/CLV fixture
  tests (PLAN verification). (4) docs/PLAYBOOK.md finalized — exact daily
  routine for user + agent. (5) `wc26 odds-check` (PLAN 4.3, optional): The
  Odds API h2h sanity check vs model 1X2, persisted monthly credit counter
  hard-capped at 150 (D007), charged before each request; needs
  ODDS_API_KEY. Dry-run on today's real match day: representative paper
  lines entered, edge report rendered, paper bet B0001 logged (USA U1.5);
  settlement tonight after the match completes the acceptance cycle.

### Fixed
- 2026-06-12: results patch keying — `_apply_patch` now joins raw and patch
  rows on canonical team ids (lenient resolution), not raw spellings.
  `wc26 data sync` writes registry names ("Czechia") while the upstream CSV
  says "Czech Republic", so the South Korea v Czechia result duplicated its
  fixture row with a null city and broke ingest. Regression test added.

- 2026-06-12: Phase 3 — prop models, walk-forward-validated. (1) Team totals
  (src/wc26/models/team_totals.py): direct marginals of the goal-engine
  grid; gates GREEN (count log-loss 1.405 vs naive 1.475, O1.5 calibration
  slope 0.87) — the only Phase 3 model cleared to price. The Phase 2 "totals
  under-dispersion" flag was quantified and re-diagnosed as a
  World-Cup-specific conditional mean miss; MATCH totals fail their gates
  and are quarantined from pricing (D019, pinned by a test). (2) Corners
  (corners.py): NB2 regression (statsmodels, D018) on engine xG gap,
  favorite prob, shrunk team shot/corner rates (leave-one-out in training),
  MD3/knockout/qualifier dummies. (3) Cards (cards.py): NB2 on shrunk
  referee career card rate, knockout, rivalry (config/rivalries.yaml,
  support-gated), team foul rates; ref-unknown → mean rate + widened
  variance + flagged output. VERDICT: corners and cards FAIL their gates
  (lose to the naive moment-matched baseline; slopes −0.72/−0.18) even after
  extending training with 462 UEFA WC-qualifier rows — quarantined as
  reference-only (D021, pinned by tests; re-gate at the Phase 6 post-group
  recalibration). Props harness in src/wc26/backtest/props.py, gates in
  tests/test_prop_gates.py; ET rows excluded from prop training AND eval
  (D017). New scrape legs wcq_uefa_2022/wcq_uefa_2026 (UEFA is the only
  confederation with ESPN team stats, D020); canceled/postponed ESPN events
  now skipped (Russia v Poland 2022). `wc26 refit` fits + versions
  corners/cards params alongside the engine; `wc26 predict` prints team
  totals, corners and cards distributions with uncertainty,
  ref-known/ref-unknown labels (optional data/manual/ref_assignments.csv)
  and explicit not-validated tags; `wc26 backtest` runs the props
  walk-forward after the 1X2 one. New deps: statsmodels (+patsy), D018.
- 2026-06-12: Phase 2 — Dixon-Coles goal engine (penaltyblog, time-decay +
  tier weights, neutral-venue handling, Elo-anchored shrinkage with the blend
  documented in docs/MODEL.md; extra-time rows excluded per D012/D014) and
  the walk-forward backtest harness (monthly refit grid, leak-free per-match
  Elo, Elo-only + de-vigged market baselines). Historical 1X2 odds ingest
  from football-data.co.uk + BetExplorer, cross-verified (D015) →
  market_odds.parquet (211 matches). Reality gates as tests: engine beats
  Elo (0.9952 vs 1.0120 log-loss), does NOT beat the market (0.9706 —
  leak-check), live 1X2 sane vs market across 71 WC26 fixtures (D016).
  New commands: `wc26 refit` (versioned params: fit date + git SHA + data
  cutoff), `wc26 predict --date` (1X2 + totals in <1 s), `wc26 backtest`.
  New deps: openpyxl, scipy (explicit), scipy-stubs (dev). Full report in
  docs/MODEL.md. First WC26 result ingested (Mexico 2-0 South Africa).
- 2026-06-12: Match-stats pipeline — ESPN JSON API ingest (corners, cards,
  fouls, shots, possession, referee) for WC 2018/2022, Euro 2024, Copa 2024
  and WC 2026 live, with permanent finished-only caching and strict parsers
  (unknown status enums and unmatched teams raise); referee card-rate table;
  `wc26 data scrape|sync` commands; automatic syncing of finished WC26
  results into the patch layer with ±1-day UTC-date tolerance. Manual stats
  entry now records yellows/reds separately.

### Fixed
- 2026-06-12: `wc26 data scrape --tournament X` no longer overwrites
  match_stats.parquet with only that tournament's rows (subset scrapes now
  merge with the existing table) and no longer crashes when a tournament has
  no finished matches yet (first match day). New alias: "D.R. Congo"
  (BetExplorer) → dr_congo.

### Changed
- 2026-06-12: FBref dropped as the stats source (Cloudflare-blocked, needs
  Chrome+Selenium) in favor of ESPN — D011. Extra-time contamination (D012)
  and cross-source date drift (D013) are now explicit, flagged invariants.
- 2026-06-11: Phase 1 data layer (most of it) — team registry for all 48
  qualified teams (groups verified vs the Dec 2025 final draw) with strict +
  lenient alias resolution; results ingest from the martj42 GitHub mirror
  (49,405 played matches 1872→2026-06-10, pandera-validated) with manual
  patch override; WC26 fixtures table (72 group matches, venues, altitude
  flags) derived from the same source; in-repo Elo with as-of-date snapshots
  for leak-free backtests (top-12 sanity-checked); `wc26 add-result` manual
  entry path and `wc26 data ingest|status|elo` commands. Decisions D008–D010.
- 2026-06-11: Phase 0 scaffold — git repo, uv project (Python 3.12, locked deps:
  penaltyblog 1.11, pandas 3.0, pandera, soccerdata, typer), docs system
  (CLAUDE.md, STATUS.md, DECISIONS.md, docs/), Makefile, `wc26` Typer CLI with
  stub commands, smoke tests.
