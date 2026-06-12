# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Newest entries on top.
Every working session must add at least one entry under `[Unreleased]`.

## [Unreleased]

### Added
- 2026-06-13 (b): strategic review actioned — market-anchor experiment,
    betting pivot, correlation guard. (1) docs/BACKLOG.md: full prioritized
    improvement backlog from the review (NOW / July-3 / rejected, with owners
    and validation paths). (2) Market-anchor experiment (D028):
    models/market_anchor.py solves DC lambdas reproducing a de-vigged 1X2
    (penaltyblog grid, scipy root-find, rho=0 → zero leak risk);
    backtest/market_anchor.py scores anchored team totals on the identical
    191-row props eval — anchored count-LL 1.3897 BEATS engine 1.4051 (naive
    1.4750), O1.5 LL 0.5971 vs 0.6053, slope 0.864 in gate; 1X2 blend weight
    w*=0.00 over 211 matches (the engine adds nothing to the market). Match
    totals stay quarantined (anchored beats naive but O2.5 slope 0.458;
    pre-registered). Runs inside `wc26 backtest`; verdict pinned by
    tests/test_market_anchor.py. DECISION: live team-total pricing pivots to
    market-anchored grids; NO new bets on raw engine edges until the
    edges/lines wiring lands (next session; needs the book's 1X2 + match-total
    quotes per match in lines.csv). (3) Correlation guard (D029): `wc26
    log-bet` refuses a second OPEN bet on the same (match, market) — the
    B0002/B0003 and B0004/B0005 nested-totals pattern; ledger stays
    append-only. (4) D030 pre-registers July-3 re-gate expectations
    (corners/cards second failure is the likely, acceptable outcome; gates
    must not be relaxed; harness-validated engine work is NOT calendar-gated).
    16 new tests (208 total), make lint clean, all existing gate numbers
    reproduced unchanged.

### Added
  - 2026-06-13: first real-money settlements. Canada v Bosnia 1-1 ingested via
    scrape/sync (results 49,408; refit @ec4661b, gates green, 192 tests).
    `wc26 settle` graded B0002 (Canada O1.5) and B0003 (Canada O2.5) as LOSSES
    (Canada scored 1 in 90'), pnl -3.00 each. clv-report: both NEGATIVE CLV
    (-5.0% / -5.5%) — closing de-vigged fair prob (0.452/0.215) below the
    taken-odds break-even, i.e. we were the wrong side of the close. n=2,
    noise. 3 bets remain open (USA v Paraguay, unplayed). Kelly stays off
    (CLV gate is 50+ bets).
### Added    
- 2026-06-12 (h): first REAL-money bets logged (Superbet, 200 RON bankroll).
    Bankroll in config/settings.yaml set 1000 → 200 (flat unit now 3.00 RON =
    1.5%). Entered real Superbet team-total lines for Canada v Bosnia and
    USA v Paraguay into data/manual/lines.csv (replacing the Phase 4 paper
    rows); `wc26 edges` flagged the BET set. Took the two cleanest edges per
    match: B0002 Canada O1.5 @2.10 (edge +0.130), B0003 Canada O2.5 @4.40
    (+0.092), B0004 Paraguay O0.5 @1.60 (+0.113), B0005 Paraguay O1.5 @3.90
    (+0.097); all 3.00 RON. Passed on the thin-EV and correlated legs
    (USA U1.5/U2.5, Bosnia U0.5/U1.5, Canada O0.5). Closing lines to be
    captured at kickoff (Canada v Bosnia 19:00 UTC 06-12; USA v Paraguay
    01:00 UTC 06-13); settle + clv-report next session

### Added
- 2026-06-12 (g): manual data path is knockout-ready (D027; closes audit
  finding 8). `wc26 add-result` now captures extra_time, the shootout
  winner (required when extra time ends level — the advancing team is
  unrecoverable later), and fouls/shots; the entered score stays the
  STORED (120') total per D012. stats_patch.csv rows are self-contained:
  they override a matching ESPN row (team pair ±1 day per D013, flipped
  orientation flips the per-side columns, blanks never erase) or become
  standalone match_stats rows (event_id `manual:<date>:<home>:<away>`)
  when ESPN never served the match; standalone rows are scrubbed and
  re-derived from the CSV on every build, so a later ESPN recovery
  converts them to overrides with no duplicates. add-result re-applies the
  patch to match_stats.parquet immediately (no scrape needed), making the
  ET flag visible to `wc26 settle` and the shootout winner to the KO-facts
  path the same minute it is entered. props_universe treats incomplete
  manual rows like incomplete qualifier rows (dropped, fail-soft) so an
  honest "-1 = unknown" cannot wedge the daily refit. 12 new tests
  (192 total); end-to-end verified in a sandbox copy (manual pens entry →
  fixtures + stats → knockout_facts resolves the winner).

### Fixed
- 2026-06-12 (g): latent ingest crash — a results_patch row for a match
  the upstream CSV doesn't carry yet (i.e. EVERY knockout result until
  upstream adds the fixture) produced a fixtures row with NaN city and
  failed FIXTURES_SCHEMA. Patch-born rows now get explicit "unknown"
  venue fields (nothing models off fixtures city/country — the bracket
  yaml is the venue truth for knockouts); regression test added.

### Added
- 2026-06-12 (f): Phase 6.1 — knockout readiness + full conformance audit.
  (1) KO-facts path: played knockout matches enter the simulator as FACTS —
  fixtures rows on/after the bracket's first R32 date split off in
  sim/tracker.py (`knockout_facts`), matched to bracket slots by team pair
  in sim/mc.py (skip sampling; every fact must be consumed in every run or
  the sim raises — a leftover fact means our finishers contradict the real
  bracket). Pens winners come from ESPN's competitor winner flag, captured
  as match_stats.shootout_winner_id (all 20 historical shootouts verified,
  e.g. WC22 final -> argentina); a level KO score without one refuses
  loudly. (2) `wc26 predict` handles knockout fixture rows: knockout=True
  for corners/cards (display only — D019/D021 quarantines unchanged), no
  matchday, "[KO — 90' probabilities; can draw]" tag; group matchday
  derivation now ignores knockout rows (cli.fixture_stage). (3) Refit
  cadence decided and encoded: daily, after every completed match day
  (D025; PLAYBOOK §1). (4) ET-contamination regression tests on
  constructed WC26 KO rows (prepare_training_data + props_universe both
  drop flagged rows, incl. ±1-day date drift). (5) docs/AUDIT.md: every
  PLAN Phase 0–5 acceptance criterion re-run, every CLAUDE.md invariant
  and risk-register row cited to code/tests; fresh-clone + working-tree
  smoke both pass (tests skip gracefully without data/processed). 16 new
  tests (180 total).

### Fixed
- 2026-06-12 (f): audit findings — stale MODEL.md "Phase 5 NOT YET BUILT"
  section rewritten; latest_model_path (cutoff, fitted_at) ordering and the
  knockout-1X2-includes-draw invariant got the tests they were missing;
  settle's ET/missing-result refusal extracted to a testable
  goals_90_from_tables (3 new tests); unused soccerdata dependency removed
  and pyarrow retroactively documented (D026). Remaining gaps filed in
  STATUS.md: add-result is not knockout-ready (no extra_time/shootout
  capture; stats_patch overlay drops rows ESPN never had) — must fix
  before June 28; PLAN 0.3 pre-commit hook never delivered (judgment call).

### Not done (time-gated, carries)
- 2026-06-12 (f): Phase 4 acceptance (settle B0001 + CLV report) still
  open — USA v Paraguay kicks off ~02:00 UTC 2026-06-13; at session time
  (16:15 UTC 2026-06-12) the fixture is unplayed, and settling would mean
  fabricating a result. The daily routine ran clean (scrape/sync: 0 new
  results; refit @508c267; backtest gates green; predict + rankings
  snapshot rendered).

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
