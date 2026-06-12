# Conformance audit — 2026-06-12

Full re-verification of every docs/PLAN.md acceptance criterion (Phases 0–5),
every CLAUDE.md domain invariant, and every PLAN risk-register row against the
actual repo. Method: every criterion was re-run or re-read in code this
session — nothing below is copied from STATUS.md on trust. Citations are
file:line as of this audit's commit.

**Verdict: PASS with 8 findings — 6 fixed in this session, 2 filed.**
Phase 4 has one acceptance step legitimately still open (time-gated on a
match that has not kicked off; see §Phase 4).

---

## Phase acceptance criteria

### Phase 0 — Scaffold: PASS (one PLAN step deviation, filed)
- *Fresh clone → `uv sync && make test` green*: re-run twice today —
  (a) `git clone` of HEAD into /tmp: 145 passed, 19 skipped, 36.6 s;
  (b) working-tree copy WITHOUT data/raw + data/processed: 161 passed,
  19 skipped. The 19 skips are the artifact-gate tests skipping gracefully
  when data/processed is absent — exactly the intended fresh-clone behavior.
- *`wc26 --help` lists commands*: verified in the fresh clone — all 11
  commands render (predict/edges/log-bet/settle/clv-report/odds-check/
  add-result/refit/backtest/sim/rankings + `data` subapp).
- *All docs exist*: CLAUDE.md, STATUS.md, CHANGELOG.md, DECISIONS.md (26
  entries), README.md, docs/{DATA,MODEL,PLAN,PLAYBOOK}.md all present.
- *settings.yaml with bankroll/unit_pct/edge_threshold/seed/decay*: present
  ([config/settings.yaml](../config/settings.yaml)), loaded through one
  validated path ([config.py:62](../src/wc26/config.py)).
- **FINDING (filed, minor)**: PLAN step 0.3 listed a pre-commit hook
  (ruff + pytest-on-push); none exists (no .pre-commit-config.yaml). The
  Phase 0 *acceptance criteria* never required it and the session protocol
  (`make test` before any commit, CLAUDE.md) covers the intent for an
  agent-operated repo. Filed as a judgment call, not silently fixed:
  adding it would add a dependency (DECISIONS entry required).

### Phase 1 — Data layer: PASS
- *`wc26 data status` prints row counts + freshness*: re-run — results
  49,407 rows (latest 2026-06-11), fixtures 72, match_stats 675, referees
  122, all built 2026-06-12.
- *Re-running ingest is idempotent*: re-ran `build_results()` twice in one
  process — results and fixtures frames compare `.equals()` True.
- *Unknown team raises with fix-it hint*:
  [teams.py:23-28](../src/wc26/data/teams.py) (UnknownTeamError names the
  aliases file); pinned by tests/test_teams.py::test_unknown_team_raises_with_hint.
- *Elo snapshot test passes*: tests/test_results_elo.py::test_full_elo_top_teams
  (top teams vs eloratings.net with documented tolerance) — green in today's
  180-test run.
- *≥600 matches with corners+cards*: 675 rows have all four corner/card
  fields (re-counted from match_stats.parquet today).

### Phase 2 — Goal engine + harness: PASS
- *Backtest report in docs/MODEL.md, three gates green*: MODEL.md §"Backtest
  reports" (211 matches). Re-ran `wc26 backtest` today: engine log-loss
  0.9953 < Elo 1.0120 (gate i), engine does NOT beat market 0.9706 (gate ii
  — by design a leak alarm), live-sanity gate iii thresholds per D016.
  Gates are tests: [test_gates.py:53,63,83](../tests/test_gates.py).
- *Predictions print in <10 s from cached data*: `wc26 predict` timed at
  1.21 s today.
- Walk-forward integrity: monthly cutoff grid fits only on `date < cutoff`
  ([harness.py:187-215](../src/wc26/backtest/harness.py)); Elo is as-of
  (`elo_history[date < cutoff]`, harness.py:201-203); prop fits raise on
  any training row ≥ cutoff ([corners.py:159-160](../src/wc26/models/corners.py),
  [cards.py:155-156](../src/wc26/models/cards.py)). Artifacts re-checked
  today: all 4 backtest parquets satisfy `cutoff <= date` on every row
  (211 + 191 + 141 + 141 rows).

### Phase 3 — Prop models: PASS
- *predict adds corners/cards/team-totals with explicit uncertainty*:
  re-ran today — mu/sd plus O/U ladders printed per market.
- *Backtest section in docs/MODEL.md*: present (team totals LIVE; match
  totals D019, corners/cards D021 quarantined with the failing numbers
  recorded honestly).
- *Cards output labels ref-known vs ref-unknown*: re-ran — "[REF UNKNOWN —
  mean rate, widened variance]" rendered; accounting pinned by
  tests/test_prop_gates.py::test_cards_ref_known_accounting.
- Quarantine pins intact: tests/test_prop_gates.py::test_match_totals_remain_quarantined
  and ::test_corners_and_cards_remain_quarantined assert the FAILURES still
  fail (a future pass breaks the test and forces a DECISIONS entry).
  Today's backtest re-run reproduced the pinned numbers (corners count-LL
  2.7189 vs naive 2.7107, cards 2.2236 vs 2.1524 — both still lose; team
  totals 1.4051 beats naive 1.4750, O1.5 slope 0.87 in [0.8, 1.2]).

### Phase 4 — Market layer: PASS except ONE step, legitimately open
- *Full dry-run on a real match day*: done 2026-06-12 (real fixtures, paper
  lines incl. American-format rows in data/manual/lines.csv, edge report,
  B0001 logged). Ledger shows exactly one open row for B0001.
- *Ledger schema test green*: tests/test_ledger.py (12 tests incl. the
  repo-ledger header check and append-only round trip).
- **OPEN**: "settle it next day, CLV report renders" — B0001 is on
  united_states v paraguay, kickoff ~02:00 UTC **2026-06-13**; at audit
  time (16:15 UTC 2026-06-12) the match has not been played and the
  fixture row is `played=False`. Settling now would fabricate a result
  (forbidden — the settle path itself refuses, see
  [cli.py goals_90_from_tables](../src/wc26/cli.py): "not in the results
  table yet"). Carries to the next session; STATUS.md step 1.
- Hard guards re-verified as tests: quarantined market refused, unpredicted
  match refused, stale (>24 h) refused, one-sided quote refused, whole-number
  line refused, unknown team raises (tests/test_lines_edges.py:52-134).
- Hand-computed de-vig + edge fixture (PLAN final acceptance): 
  tests/test_lines_edges.py::test_hand_computed_devig_and_edge.

### Phase 5 — Simulator & rankings: PASS
- *`wc26 rankings` runs in <60 s*: 6.0 s today (20k runs).
- *Recalculates after a result; eliminated team → 0% everywhere*: gate test
  on constructed fixtures (test_sim_gates.py::test_eliminated_team_zero_everywhere_after_result_lands)
  — exact zeros, not approximations.
- *Snapshot diffing works*: tests/test_snapshots.py (save/previous/diff +
  mismatched-team-set rejection). Live `--diff` printed "no earlier
  snapshot" today — correct: all sessions so far are dated 2026-06-12, so
  only one snapshot file exists.
- *Gates green*: test_sim_gates.py — P(champion) sums to 1, bit-determinism
  under fixed seed, decided groups collapse to {0,1}, three-way-tie
  tiebreakers (test_standings.py).

---

## Domain invariants (CLAUDE.md) — enforcement points

| Invariant | Enforced at | Test |
|---|---|---|
| All probabilities 90' (D004); KO can draw | engine has NO stage parameter — same grid prices group + KO ([goal_engine.py:244-269](../src/wc26/models/goal_engine.py)); ET/pens exists only in [mc.py:114-132](../src/wc26/sim/mc.py), unreachable from markets | test_goal_engine.py::test_grid_invariants (draw > 0.05); test_ko_facts.py::test_knockout_1x2_includes_draw (added by this audit) |
| Decimal-only odds; American at boundary | [odds.py:16-54](../src/wc26/markets/odds.py); every entry point goes through parse_odds (lines.py:151, cli.py settle/log-bet) | test_odds.py (incl. −110, magnitude guard) |
| De-vig before comparing (D005), via penaltyblog | [edges.py:22-26](../src/wc26/markets/edges.py) `calculate_implied(method="multiplicative")`; market baseline likewise ([baselines.py:81](../src/wc26/backtest/baselines.py)). No hand-rolled normalization in src/wc26/markets (grepped) | test_lines_edges.py::test_hand_computed_devig_and_edge |
| No fit/eval on data ≥ match date | harness walk-forward (above); refit cutoff=tomorrow includes only played matches ([cli.py refit](../src/wc26/cli.py)); prop fits raise on leak | test_goal_engine.py::test_prepare_is_strictly_before_cutoff; artifact re-check above |
| Canonical team IDs only; unknown = raise (D008 strict/lenient split) | [teams.py:74-82](../src/wc26/data/teams.py); WC26 fixtures strictly resolved ([results.py:162-164](../src/wc26/data/results.py)); KO facts re-check registry ([tracker.py:159-161](../src/wc26/sim/tracker.py)) | test_teams.py; test_lines_edges.py::test_unknown_team_raises_strict |
| Times UTC; venue-local only at display | all stored dates are normalized UTC dates (espn.py:219, ledger ts_utc, lines ts_utc converted lines.py:135-136). No venue-local display exists yet — the CLI prints dates only, so nothing violates the direction of the rule | — (nothing to pin until local-time display is built) |
| Ledger append-only; flat stakes; no Kelly until CLV>0 over 50+ | [ledger.py:91-103](../src/wc26/markets/ledger.py) append mode + header refusal; `kelly_enabled: true` refuses to even load ([config.py:65-68](../src/wc26/config.py)); re-settling blocked (cli.py settle) | test_ledger.py append/header tests; test_smoke settings load |
| Home advantage only USA/Mexico/Canada; altitude flag | groups: neutral flag from fixtures (host games non-neutral upstream), ha applied only when `neutral=False` (goal_engine.py:263); knockouts: [mc.py:106-111](../src/wc26/sim/mc.py) + HOST_COUNTRY ([bracket.py:37-41](../src/wc26/sim/bracket.py)); altitude [results.py:42,165](../src/wc26/data/results.py) | test_sim_gates.py::test_ko_orientation_host_home_advantage; test_goal_engine.py::test_home_advantage_only_when_not_neutral |
| Small-data humility (Elo-anchored shrinkage) | [goal_engine.py:210-226](../src/wc26/models/goal_engine.py) | test_goal_engine.py::test_elo_anchor_prices_unseen_team, ::test_shrinkage_pulls_sparse_team_toward_anchor |
| pandera at every DataFrame boundary | RESULTS/FIXTURES (results.py:44-76), MATCH_STATS (espn.py:97-121), TRAIN (goal_engine.py:44), PROPS (prop_features.py:26), backtest eval (harness.py:55), RANKINGS (mc.py:40), LEDGER (ledger.py:57). lines.csv is row-wise hard-error validation rather than pandera — every malformed field raises LineError; intent (fail loudly at ingest) is met | suite-wide; schema violations raise in tests |
| Model files versioned SHA+cutoff; latest by (cutoff, fitted_at) | save fields (goal_engine.py:100-122); [latest_model_path:272-287](../src/wc26/models/goal_engine.py) reads the payload, not the filename | test_goal_engine.py::test_latest_model_path_orders_by_cutoff_then_fitted_at (added by this audit — was untested) |
| Fixed seed; deterministic fits | settings.yaml:9 is the single seed source; fits sorted+MLE | test_sim_gates.py::test_deterministic_under_fixed_seed; test_ko_facts.py::test_facts_deterministic_and_gates_unaffected; test_goal_engine.py::test_fit_is_deterministic |
| penaltyblog only for DC/de-vig; statsmodels only for NB2 (D018) | grep: no Poisson likelihood outside penaltyblog calls; negbin.py wraps statsmodels | test_negbin.py planted-signal recovery |
| Futures unbettable (PLAN 5.5) | grep: zero imports of wc26.sim anywhere in src/wc26/markets; PRICEABLE_MARKETS frozen to team_total ([lines.py:42](../src/wc26/markets/lines.py)) | test_lines_edges.py::test_quarantined_markets_are_refused |
| Odds API budget cap | charge-before-request with monthly persistence ([odds_api.py:45-65](../src/wc26/data/odds_api.py)) | test_odds_api.py (cap refusal, persistence, month rollover) |
| No dependency without DECISIONS entry | pyproject diffed against DECISIONS this audit | see findings 4–5 (D026) |

## Risk register — guard verification

| Risk | Guard verified at |
|---|---|
| Name drift across sources | UnknownTeamError + alias yaml (teams.py); ESPN boxscore mismatch raises (espn.py:236-242); sync raises on unmatched fixture (sync.py:75-82) |
| FBref layout change / ban | moot — ESPN replaced FBref (D011); raw responses cached forever (espn.py:153-191); `add-result` manual path tested (test_manual.py) |
| Upstream CSV lag | results_patch.csv wins on canonical-id keys (results.py:103-132, test_patch_matches_on_canonical_ids_not_spelling); `wc26 data sync` (test_sync.py idempotency) |
| Backtest leakage | walk-forward only (harness.py); gate ii TREATS beating the market as failure (test_gates.py:63); as-of Elo (harness.py:201) |
| Odds-format mistakes | decimal-only internals, boundary parser with negative-American tests (test_odds.py) |
| Knockout draw forgotten | engine stage-agnostic + draw-mass tests (see invariants table, row 1) |
| Schema drift | pandera at boundaries (table above); ESPN unknown final-status enum raises (espn.py:147-150, test_espn.py) |
| Ledger corruption / revisionism | append-only + canonical-header refusal + in-git (ledger.py:91-103; test_ledger.py); re-settle blocked (cli.py) |
| Non-reproducible fits | seed in settings; SHA+cutoff stamps; determinism tests (invariants table) |
| Dependency rot | uv.lock pinned; audit diff → D026 |
| Overbetting on noise | 5% edge floor + flat stakes in settings; kelly_enabled load-time refusal (config.py:65-68); BET flag only at threshold (cli.py edges) |
| Agent context loss | docs system exercised by this very session (STATUS → smallest next task → this audit) |

---

## Findings

1. **docs/MODEL.md said "Tournament simulator (Phase 5) — NOT YET BUILT"**
   while Phase 5 has been live since 2026-06-12. Stale doc. **FIXED**
   (section rewritten with the live description + Phase 6.1 KO facts).
2. **`latest_model_path` (cutoff, fitted_at) ordering had no test** despite
   being a documented bug fix (D023 note). **FIXED**:
   test_goal_engine.py::test_latest_model_path_orders_by_cutoff_then_fitted_at
   (filenames chosen so a filename sort picks wrong in both dimensions).
3. **Risk-register row "test asserting knockout 1X2 probs include draw" had
   no knockout-context test** (test_grid_invariants covers the math but not
   the KO framing). **FIXED**: test_ko_facts.py::test_knockout_1x2_includes_draw.
4. **soccerdata was an unused dependency** — planned for FBref, superseded
   by ESPN (D011) before first import; grep found zero usage. **FIXED**:
   `uv remove soccerdata` (D026).
5. **pyarrow had no DECISIONS entry** (parquet engine since Phase 1).
   **FIXED**: retroactively documented in D026. (pandas-stubs/types-pyyaml/
   scipy-stubs are dev-only typing stubs riding D015/D002's rationale;
   accepted without separate entries.)
6. **The settle command's ET-refusal / result-missing logic was untestable
   inline** (buried in the Typer command with hardwired paths). **FIXED**:
   extracted to `goals_90_from_tables` ([cli.py](../src/wc26/cli.py)) with
   three new tests (ET refusal, missing result refusal, correct 90' read
   incl. ±1-day date drift).
7. **PLAN 0.3 pre-commit hook never delivered** — **FILED** (see Phase 0;
   adding it needs a new dev dependency = DECISIONS entry; Makefile +
   session protocol currently cover the intent).
8. **`wc26 add-result` is not knockout-ready** — **FILED in STATUS.md**:
   (a) it cannot record `extra_time` or a shootout winner, so a manually
   entered KO result that went to ET would be missing the flag that keeps
   it out of 90' training (D012) and the winner the simulator needs;
   (b) stats_patch rows for matches ESPN never served are dropped by the
   overlay (`DataFrame.update` only modifies existing rows,
   [espn.py:_apply_stats_patch](../src/wc26/data/espn.py)) — the manual
   stats path silently no-ops when ESPN is fully down for a match. Neither
   bites during the group stage (ESPN has served every WC26 match so far,
   and group matches have no ET); both must be fixed before June 28 (R32).
   Design choice involved (patch rows becoming standalone rows needs a
   completeness contract), hence filed, not rushed tonight.

## Phase 6.1 additions verified alongside (this session)
KO-facts path (tracker.knockout_facts → mc.run_simulation ko_facts), ESPN
shootout_winner_id (all 20 historical pens matches verified correct, e.g.
WC22 final → argentina), predict KO handling (fixture_stage), D025 refit
cadence, ET regression tests on constructed WC26 KO rows. 180 tests green,
`make lint` (ruff + mypy --strict) clean after all audit fixes.
