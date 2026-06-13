# Project Status

> Single source of truth for "where are we". Update before ending every session.

## Current phase
**Phase 6 — IN PROGRESS. 6.1 (knockout readiness) DONE 2026-06-12; Phase 4
acceptance now CLOSED (2026-06-13: USA v Paraguay 4-1 settled all 5 bets,
clv-report renders). The 6.2 recalibration checkpoint is calendar-gated
(~2026-07-03, after the group stage).** Live betting RESUMES under market-anchored
pricing (D032 wired edges/log-bet to the book's 1X2; no anchor = no bet).

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
  1. **Resume betting under anchored pricing (D032 DONE)** — the daily loop is
     now: enter the book's 1X2 in data/manual/anchors.csv AND the team-total
     quotes in lines.csv (PLAYBOOK §3), then `wc26 edges` (anchored) →
     `wc26 log-bet` (refuses any match with no anchor). First live anchored
     bets pending the next match day's quotes.
  2. **Automated kickoff odds snapshot (backlog #6, Odds API cap now 400 /
     D031)** — so a missed manual capture (as happened 2026-06-13) no longer
     loses CLV: snapshot 1X2 + match-total at each kickoff as a fallback
     anchor (doubles as an auto-anchor source for #1). The 2026-06-13 miss is
     exactly the failure this prevents. NEXT agent task.
  3. **WC scoring-environment engine fix (backlog #4, D019/D030)** — not
     calendar-gated; harness-validated on pre-2026 data. Improves the engine
     that still supplies rho + corners/cards features even under anchoring.
  4. User commitments (see docs/BACKLOG.md): collect the historical prop-line
     sample into data/manual/historical_prop_lines.csv (BACKLOG #3) — feeds
     the data-derived edge_threshold (#8). Line shopping (#5) DEFERRED.
  4. **Phase 6.2 recalibration checkpoint — NEXT MILESTONE, ~2026-07-03**
   (after the 72 group matches; do NOT start early — pre-registered
   expectations in D030): compare predicted vs realized over the group
   stage; re-gate match totals (D019) and corners/cards (D021) through the
   walk-forward harness (a pass needs a new DECISIONS entry, never a silent
   flip); add the knockout flag + group-state stakes feature (elimination
   risk from sim/tracker.py TeamStatus) to the cards model; flip the
   simulator's R32 slots from projected to actual (the KO-facts path from
   6.1 is the mechanism). NOT calendar-gated (D030): the D019 WC
   scoring-environment engine fix (backlog #4) — harness-validated on
   pre-2026 data, can ship any day.

## Blockers
None. Betting resumes under anchored pricing (D032). 0 bets open — all 5
settled. Real-money CLV 4/4 NEGATIVE (mean -12.4%): B0002 -5.0%, B0003 -5.5%
(captured close), B0004 -12.5%, B0005 -26.5% (T-2h 1X2 anchor, degraded —
prop close missed at kickoff). n=4, but 4/4 is mechanism-consistent with the
D028 adverse-selection finding — and anchored pricing would have refused the
over side of all of them (validated end-to-end, D032).

## Daily during tournament (~10 min, see docs/PLAYBOOK.md for the full version)
`uv run wc26 data scrape --tournament wc2026 && uv run wc26 data sync` →
`wc26 data status` → `uv run wc26 refit` → `uv run wc26 backtest && uv run
pytest` (re-check gates) → `uv run wc26 predict` → settle yesterday's open
bets (closing quotes!) → user enters today's 1X2 anchors (anchors.csv) +
team-total lines (lines.csv) → `wc26 edges` →
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
  - Ledger: ledger/bets.csv — all 5 settled. Real: B0002/B0003/B0005 lost,
    B0004 won; all 4 negative CLV. B0001 paper (lost). 0 open.

## Last session summary
  - 2026-06-13 (d): wired market-anchored pricing into the live path (D032,
    backlog #1) — betting un-paused. New data/manual/anchors.csv (book's 1X2
    per match, markets/anchors.py parser, same guards as lines.py, orientation
    flip handled). `wc26 edges` now prices team totals from the DC grid solved
    to the de-vigged anchor 1X2 (rho from the latest engine fit), edge =
    anchored_p - prop fair_p; engine P(over) shown as context only; no anchor
    => unpriceable, can't be flagged BET. `wc26 log-bet` refuses a bet whose
    match has no anchor ("no anchor, no bet") and stamps model_version
    "anchor+<engine>". Validated end-to-end on the real fit + recalled USA v
    Paraguay 1X2: anchored over-edge NEGATIVE on B0004 (-0.7%) and B0005
    (-2.8%) where the engine said +9.4%/+7.2% — the wiring refuses exactly the
    bets that lost CLV. Also shipped backlog #14 (clv-report splits real money
    from paper — real CLV -12.4%, paper excluded). 14 new tests (222 total),
    lint clean, all gates green. Next: auto kickoff-snapshot (#6), engine WC
    offset (#4).
  - 2026-06-13 (c): USA v Paraguay finished 4-1 (results 49,408 -> scraped/
    synced; refit @8678a8d on 9,504 matches, ha 0.235; backtest + 208 tests
    green, all gate numbers unchanged). Settled the final 3 open bets: B0004
    Paraguay O0.5 WON (+1.80), B0005 Paraguay O1.5 LOST (-3.00), B0001 USA
    U1.5 paper LOST. The closing prop quotes were MISSED (user asleep at the
    ~01:00 UTC kickoff) — exactly the manual-capture fragility the review
    flagged. Recovered CLV by anchoring the user's recalled T-2h 1X2
    (2.12/3.30/4.09) through the new market-anchor module (D028), engine-free:
    B0004 CLV -12.5%, B0005 -26.5% (both flagged DEGRADED in the ledger note;
    the book's 1X2 and O/U disagreed ~7pts on the total but both bets are
    negative-CLV under either reconstruction). Real-money CLV now 4/4 negative
    — strengthens the D028 pivot. clv-report renders (note: it mixes the
    paper B0001's 15-unit notional into the headline ROI; real-money staked is
    12 RON, pnl -7.20). Phase 4 acceptance CLOSED. New bets remain paused.
  - 2026-06-13 (b): strategic review actioned (docs/BACKLOG.md = the full
    prioritized improvement list). Built and ran the market-anchor experiment
    (D028): team totals priced from DC grids solved to reproduce the de-vigged
    market 1X2 BEAT the engine on the identical 191-row walk-forward eval
    (count-LL 1.3897 vs 1.4051, naive 1.4750; O1.5 slope 0.864 in gate), and
    the optimal 1X2 engine/market blend weight is w*=0.00 over 211 matches —
    raw `model_p − fair_p` edges are noise. PIVOT: live team-total pricing
    moves to market-anchored grids; new bets paused until `wc26 edges` is
    rewired (next task 2). Match totals stay quarantined (anchored O2.5 slope
    0.458; pre-registered). Correlation guard added (D029): one open bet per
    (match, market) enforced at log-bet. D030 pre-registers July-3 re-gate
    expectations. 16 new tests (208 total), lint clean, gate numbers
    reproduced unchanged. Open bets B0001/B0004/B0005 untouched (settle on
    the real result with closing capture).
  - 2026-06-13: settled the first two real-money bets. Canada v Bosnia finished
    1-1 (ingested: results 49,408). B0002 Canada O1.5 and B0003 Canada O2.5
    both LOST (Canada scored 1) — pnl -3.00 each. Both also had NEGATIVE CLV
    (B0002 -5.0%, B0003 -5.5%): the de-vigged closing fair prob (0.452 / 0.215)
    came in below what the taken odds needed, so we were on the wrong side of
    the close, not just unlucky. n=2, far below the 50-bet read threshold —
    noise, not a verdict. Daily routine clean: refit @ec4661b (9,510 matches,
    ha 0.235), gates green, 192 tests pass, predict/rankings/sim rendered.
    3 bets still open (all USA v Paraguay, unplayed). Phase 4 acceptance still
    not ticked.
  - 2026-06-12 (h): went LIVE. Set bankroll to 200 RON (unit = 3.00). Entered
    real Superbet team-total lines for Canada v Bosnia + USA v Paraguay, ran
    edges, and logged the first four real-money bets: B0002 Canada O1.5 @2.10,
    B0003 Canada O2.5 @4.40, B0004 Paraguay O0.5 @1.60, B0005 Paraguay O1.5
    @3.90 (all 3.00 RON, all on the strongest edge+EV rows). Passed on
    thin-EV / correlated legs. Closing lines to capture at kickoff; settle +
    CLV next session. Phase 4 acceptance still not ticked — completes once
    these settle.
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
- [x] Phase 4 — Market layer (edges, ledger, CLV) — acceptance MET 2026-06-13:
      all 5 bets settled (USA v Paraguay 4-1), clv-report renders. Pricing
      pivots to market-anchored under D028 (live wiring = Phase 6 next task).
- [x] Phase 5 — Tournament simulator & country rankings
- [ ] Phase 6 — Tournament ops: 6.1 knockout readiness DONE (KO facts, KO
      predict, D025 cadence, audit); 6.2 recalibration checkpoint
      calendar-gated ~2026-07-03 (next task 4)
