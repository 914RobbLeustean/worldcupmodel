# Decisions (ADR-lite)

Numbered, dated, append-only. One entry per non-obvious choice: what we decided and why.
Reversing a decision = new entry referencing the old one, never edit history.

## D001 — 2026-06-11 — Repo layout & docs system
Single-package src layout (`src/wc26`), docs as first-class citizens
(STATUS/CHANGELOG/DECISIONS + docs/). Rationale: the project is operated by
AI agents across sessions; resumability depends on docs, not memory. The full
build plan lives at docs/PLAN.md.

## D002 — 2026-06-11 — uv for environment & locking
`uv` manages Python (3.12 pinned via .python-version) and dependencies
(uv.lock committed). Rationale: deterministic installs, no pip drift; a fresh
clone reproduces the exact environment during the tournament.

## D003 — 2026-06-11 — penaltyblog for Dixon-Coles & odds math
Use penaltyblog (resolved 1.11.x) for goal models and implied-probability
utilities instead of hand-rolling. Rationale: maintained (2026), Cython-fast,
widely used; hand-rolled Poisson likelihood/de-vig math is where silent money-
losing bugs live.

## D004 — 2026-06-11 — All probabilities settle on 90 minutes
Every model output is the 90-minute result (knockout matches can draw).
Rationale: betting markets for 1X2/totals/props settle on regulation time.
The tournament simulator layers an explicit extra-time/penalties resolution on
top only for advancement, never for pricing bets.

## D005 — 2026-06-11 — Multiplicative (proportional) de-vig for v1
Remove bookmaker margin by normalizing implied probabilities proportionally.
Rationale: simple, standard, adequate for two-way prop markets at soft books.
Known limitation: ignores favorite-longshot bias; revisit with Shin/power
method if CLV tracking suggests systematic skew (new decision entry then).

## D006 — 2026-06-11 — Append-only bet ledger in git
ledger/bets.csv is append-only; corrections are new correcting rows.
Rationale: honest CLV/ROI accounting requires an auditable, tamper-evident
record; git history makes revisionism visible.

## D007 — 2026-06-11 — Manual line entry instead of paid odds feed
Prop lines (corners/cards/team totals) are typed into data/manual/lines.csv
from the user's sportsbook. Rationale: free-data constraint; The Odds API free
tier (500 credits/mo) doesn't carry prop markets. Free-tier API reserved for
occasional h2h sanity checks with a hard budget counter.

## D008 — 2026-06-11 — Strict team resolution for WC26, lenient for history
The registry (config/teams.yaml) strictly covers the 48 qualified teams; any
WC26-facing pipeline resolves strictly (UnknownTeamError). The full ~300-team
historical universe (needed only for Elo) uses resolve_lenient(): known
aliases canonicalize, everything else passes through as a slug. Rationale:
mapping 150 years of defunct nations buys nothing — historical teams never
touch pricing code.

## D009 — 2026-06-11 — Fixtures derived from results CSV, not manual schedule
The martj42 results CSV already carries all 72 WC26 group fixtures with
venues (NA scores until played), so fixtures.parquet is generated from it
instead of hand-entering data/manual/schedule.csv. Manual schedule entry is
now only needed for knockout slots/kickoff times when those matter (Phase 5).
Altitude flag derived from city (Mexico City, Zapopan/Guadalajara).

## D010 — 2026-06-11 — Results source: GitHub mirror of martj42 dataset
Download results.csv from raw.githubusercontent.com/martj42/international_results
rather than Kaggle (no API key needed, same maintained data, found to be
current through yesterday's matches).

## D011 — 2026-06-12 — ESPN JSON API replaces FBref for match stats
FBref now sits behind Cloudflare (plain HTTP gets 403) and soccerdata's FBref
reader requires a real Chrome install + Selenium. ESPN's site API
(site.api.espn.com) serves the same match-level fields we need — corners,
yellows/reds, fouls, shots, possession, referee — as plain JSON for
internationals back to 2018, no key, no browser. Implemented in
src/wc26/data/espn.py with permanent caching (finished matches/days only) and
a 1.2 s request pause. Supersedes the FBref plan in docs/PLAN.md Phase 1.4;
the "scrape only via soccerdata" rule in CLAUDE.md is amended accordingly.
Trade-off: ESPN team-stat coverage for smaller qualifiers is spottier than
FBref; acceptable — the prop models train on majors.

## D012 — 2026-06-12 — Extra-time contamination flagged at ingest
ESPN scores/stat totals for knockout matches include extra time (verified:
WC22 final stored as 3-3, which is the 120' score; the 90' score was 2-2).
The martj42 results CSV has the same property. Every match_stats row carries
`extra_time` (derived from ESPN's final-status enum; unknown enums raise).
RULE for Phase 2/3: models that price 90-minute markets must exclude or
explicitly adjust `extra_time` rows — never train on them as-is. Elo is
unaffected (outcome after pens counts as a draw, which our pipeline already
produces since shootout matches carry level scores).

## D013 — 2026-06-12 — Match keys must tolerate ±1 day across sources
ESPN match dates are UTC kickoff dates; the results CSV uses local dates.
Late-evening kickoffs in the Americas land on the next UTC day, so joining
match_stats to results on exact (date, home, away) will silently drop
matches. Any cross-source join goes through a tolerant matcher (team pair +
date within ±1 day). Applies to Phase 2/3 feature joins and result syncing.

## D014 — 2026-06-12 — Extra-time handling in goal-engine training
90-minute models must not train on scores that include extra time (D012).
Handling, by era:
- 2018+ majors (incl. WC26 live): match_stats carries a verified per-event
  `extra_time` flag → flagged rows are EXCLUDED from training (matched back
  to results by team pair ±1 day, D013). Exclusion over adjustment: the 90'
  score is not recoverable from our sources' totals, and it is ~20 rows.
- Pre-2018: no flag exists (ESPN coverage starts 2018). Contamination is
  accepted and quantified: only knockout matches of majors can be affected
  (~1% of all internationals), of which ~25-30% went to ET (~0.3% of rows);
  shootout matches are stored with level scores and settle as draws, which is
  already the correct 90' outcome, halving the damage again. With 18-month
  decay half-life, pre-2018 rows carry <3% weight in any 2026 fit. Building a
  stage-inference heuristic across 150 years of formats was judged more
  dangerous than this residual bias.
- Backtest evaluation: an ET-flagged match was level after 90' by
  construction (single-match knockouts) → outcome scored as a draw. Verified
  against football-data.co.uk's separate 90' scores (HGFT/AGFT) for all 10
  WC18/WC22 ET matches in tests/test_market_odds.py.

## D015 — 2026-06-12 — Historical 1X2 odds: football-data.co.uk + BetExplorer
Market baseline odds (Phase 2 backtest) come from two free sources:
- WC 2018 + WC 2022: football-data.co.uk WorldCup2026.xlsx (per-tournament
  sheets, average/max odds + named books, plus true 90' scores).
- Euro 2024 + Copa América 2024 (archives) and WC 2026 (live fixtures page):
  BetExplorer average odds (static pages + their league-results AJAX
  endpoint), cached forever under data/raw/odds/.
Cross-verified on overlapping matches (WC22 final, 3rd-place; ~1.5% apart)
and against known lines (WC18 opener). LIMITATION: these are average
bookmaker odds collected near kickoff, not strictly Pinnacle closing — the
market baseline is a closing proxy and is documented as such in MODEL.md.
New dependencies: openpyxl (xlsx parsing), scipy made explicit (Elo baseline
draw-width MLE; already transitive via penaltyblog), scipy-stubs (dev).

## D016 — 2026-06-12 — Live sanity gate thresholds (gate iii)
The live model-vs-market gate catches insanity (team mix-ups, inverted strong
favorites, broken home advantage), not honest disagreement. Initial guess of
0.15 max per-outcome diff was too tight: inspecting the 2026-06-12 snapshot
(71 fixtures) showed mean diff 0.074 but worst 0.213 (brazil v morocco —
market prices the brand, Elo/results price Morocco's form; model still keeps
Brazil modal). Thresholds set to: max per-outcome diff ≤ 0.25, mean ≤ 0.10,
and any market favorite ≥ 0.55 must also be the model's modal outcome.
Revisit only with a DECISIONS entry; CLV tracking (Phase 4) is the real
adjudicator of who is right on the big deviations.

## D017 — 2026-06-12 — Extra time and prop models: exclude, both sides
Corners/cards/fouls totals in match_stats include extra time for `extra_time`
rows (D012), and the 90' split is not recoverable from ESPN's totals. The
90-minute prop models therefore EXCLUDE ET rows from BOTH training and
evaluation (20 of 211 majors rows; the eval universe is 191). Exclusion over
adjustment for the same reason as D014; unlike 1X2 (where an ET match is a
known draw), a 90' corner/card count for an ET match is simply unknown, so
these matches cannot be scored at all. `props_universe()` in
src/wc26/models/prop_features.py is the single entry point and drops them.

## D018 — 2026-06-12 — statsmodels for NB2 prop regressions
New dependency: statsmodels 0.14 (with patsy). The corners/cards models are
NB2 negative-binomial regressions (Var = mu + alpha*mu^2) fit by MLE —
exactly statsmodels' NegativeBinomial; hand-rolling count-regression MLE is
the same class of bug risk D003 exists to avoid. penaltyblog stays the only
source of goal-model/de-vig math. Also used for the calibration-slope gate
statistic (a one-parameter logistic recalibration). Fits are warm-started
from a Poisson GLM; an alpha MLE on the boundary (<1e-3, i.e. no conditional
overdispersion) collapses explicitly to the Poisson solution rather than
reporting a fake non-convergence.

## D019 — 2026-06-12 — Totals verdict: team totals ship, match totals don't
Phase 2 flagged engine match-totals as "under-dispersed vs market". The
Phase 3 walk-forward quantification (191 non-ET majors) shows the real
problem is a conditional MEAN miss, not grid variance:
- Team-totals marginals are healthy: count log-loss beats the naive
  Poisson-at-majors-mean baseline and the O1.5 calibration slope is in
  gate range. Empirical home/away goal covariance is ~-0.14 (the grid's is
  ~0), so the grid is not too narrow on the sum either.
- The engine under-predicts World Cup scoring specifically (pred 2.20 vs
  realized 2.66 goals/match over WC18+WC22; Euro24/Copa24 are fine), mostly
  on the favorite's side — Elo-anchored shrinkage compresses mismatch
  lambdas. Match-total O2.5 calibration slope ≈ 0.13 pooled (0.28/0.17/-0.18
  within tournament): the match-totals signal is too weak to price.
DECISION: team totals (home/away O/U) ship behind their green gates; match
totals O/U is NOT priceable — `wc26 predict` prints it with an explicit
"NOT validated" tag and the markets layer (Phase 4) must refuse match-total
lines. No rescaling correction is applied: a mean-level rescale would not
fix a 0.13 slope, and engine retuning belongs to a Phase 6 recalibration
checkpoint with the 1X2 gates re-run. Numbers in docs/MODEL.md.

## D020 — 2026-06-12 — Corners/cards sample: UEFA WC-qualifier extension
The PLAN escape hatch invoked: majors-only training (59 rows at the first
usable cutoff) produced corners/cards fits whose coefficients whipped
cutoff-to-cutoff and lost to the naive baseline. Added fifa.worldq.* legs to
espn.py TOURNAMENTS — but UEFA ONLY: probing ESPN (2026-06-12) showed
CONMEBOL/AFC/CAF/CONCACAF qualifier summaries carry officials but NO team
stats, so only fifa.worldq.uefa is ingestible. Two cycles: 2021-03→2022-06
(stats, no officials — like WC18) and 2025-03→2026-03 (stats + officials).
Qualifier rows are TRAINING-ONLY (a `qualifier` level dummy separates their
environment; matchday/knockout forced to baseline; incomplete rows dropped
rather than fatal): the gates stay defined on the 2018→2024 finals sample
and we never price qualifier lines. Naive baselines keep using finals rows
only.

## D021 — 2026-06-12 — Corners/cards gate verdict: built, FAILED, quarantined
The PLAN 3.4 gates ran on 141 walk-forward finals matches (WC18 July KOs,
WC22, Euro24, Copa24) with training extended by 462 UEFA qualifier rows
(D020): corners count log-loss 2.719 vs naive 2.711 (LOSES), O9.5 slope
-0.72; cards 2.224 vs 2.152 (LOSES), O3.5 slope -0.18. Predicted means are
essentially uncorrelated with outcomes (corners -0.12, cards -0.07, cards
ref-known slice -0.16) while the LEVEL is right — and the same code recovers
planted signal on synthetic data (tests), so this is absence of evidence of
per-match signal, not a bug. Tournament-level shocks (Euro24 ran hot on both
stats) dominate and are unpredictable pre-tournament. DECISION: the fitted
NB2 models ship as REFERENCE ONLY — `wc26 predict` prints them with a "NOT
validated" tag, Phase 4 must refuse corners/cards lines, and
tests/test_prop_gates.py pins the failures (a future pass requires a new
DECISIONS entry, not a silent flip). Further feature surgery was rejected as
backtest fishing. Re-gate at the Phase 6 post-group recalibration when ~70
WC26 matches and richer referee careers exist. The only Phase 3 model
cleared to price is TEAM TOTALS.

## D022 — 2026-06-12 — Market-layer definitions: edge, CLV, ledger format
Phase 4 fixes the quantities the money decisions run on:
- EDGE = model_p − fair_p (probability points), where fair_p is the
  multiplicative de-vig (D005) of BOTH quoted sides; settings.edge_threshold
  (5%) gates on this. EV = model_p × decimal_odds − 1 is printed for context
  (a positive edge can still have negative EV once the vig is paid — such
  quotes are correctly not flagged).
- CLV per bet = odds_taken × fair_closing_p − 1 with fair_closing_p from the
  de-vigged manually-entered closing two-way quote: positive = beat the
  close. clv-report shows mean and stake-weighted CLV, ROI, and win rate vs
  mean bet-on model_p (a bucketed reliability curve is noise below ~50 bets).
- lines.csv: one row per quoted side; both sides required (refused
  otherwise) — de-vig needs the pair. Markets keyed `team_total:<team>`;
  the priceable set is a frozen constant (PRICEABLE_MARKETS in
  src/wc26/markets/lines.py) so un-quarantining a market is a code change
  with a DECISIONS entry, not a data edit. Half-goal lines only (pushes out
  of scope for v1).
- ledger/bets.csv schema finalized BEFORE the first bet (bet_id + side +
  match_date + closing both-sides odds + goals_90 added to the Phase 0 draft
  header): a bet's life is one `open` row then one `settled` row, same
  bet_id, last row per bet_id wins; `wc26 settle` blocks re-settling
  (corrections = manual new rows, D006). Settlement takes goals_90 — the 90'
  count (D004) — read from results automatically only when match_stats shows
  no extra_time flag, else --goals is mandatory (stored ET scores are 120',
  D012).
- log-bet requires the market to exist two-sided in lines.csv so the logged
  edge uses the identical de-vig as `wc26 edges` (no one-sided edge guesses);
  odds actually taken may override the quoted side's price.
