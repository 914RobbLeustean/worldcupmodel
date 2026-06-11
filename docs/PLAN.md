# World Cup 2026 Edge Model — Build Plan

## Context

Robert wants a prediction model for World Cup 2026 (started June 11, 2026 — tournament is live, so speed matters) that finds +EV bets against sportsbook lines. Decisions already made with the user:

- **Markets**: match props — corners, cards, team totals (softest lines, best edge-to-effort). Match result/totals predictions are built anyway as the foundation and sanity check.
- **Stakes**: real money, small (flat 1–2% units, no Kelly until proven CLV).
- **Data**: free only. Consequence: prop odds are **manually entered** from the user's book into a file; the system computes edges. The Odds API free tier (500 credits/mo) is used sparingly for match-odds sanity checks only.
- **Form**: Python pipeline + CLI. No web app.
- **Success metric**: closing line value (CLV) and calibration (Brier/log-loss vs. de-vigged market), NOT short-term profit.

The project must be **agent-resumable**: any agent in any session reads the docs, knows exactly where the project stands, and can pick up the next task. Docs system: `CLAUDE.md` (how to work here), `STATUS.md` (where we are), `CHANGELOG.md` (what changed), `DECISIONS.md` (why), `docs/DATA.md` (source contracts).

**Location**: new repo at `/Users/robert/worldcup-model` (NOT inside the iOS repo that is the current cwd). Initialize git immediately.

## Verified research (June 2026)

- **[penaltyblog](https://github.com/martineastwood/penaltyblog) v1.9.x** — maintained (Feb 2026), Cython-optimized Dixon-Coles / bivariate Poisson + utilities to convert fitted models into 1X2, totals, AH, correct-score probabilities, plus implied-probability (de-vig) functions. **Use it; do not hand-roll the Poisson math.**
- **[martj42 Kaggle dataset](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017)** — international results 1872→2026, ~49k matches, maintained, has `neutral` flag and tournament names. One-time CSV download; during the tournament it lags days behind → we need our own `add-result` command.
- **[soccerdata](https://soccerdata.readthedocs.io/)** — FBref scraper with local caching and rate-limit pauses. FBref enforces strict rate limits (~1 req/6s) and bans abusers. Scrapers break when the site changes → pin version, cache every raw response permanently, treat scraping as one-time ingestion + tiny incremental updates.
- **[The Odds API](https://the-odds-api.com/liveapi/guides/v4/)** — free tier = 500 *credits*/mo, cost = markets × regions per call. h2h/totals available; corners/cards props effectively not available on free tier. Confirms manual line entry design.
- **WC 2026 format**: 48 teams, 12 groups of 4, top 2 + 8 best third-placed advance to a round of 32; 104 matches; venues in USA/Mexico/Canada (incl. altitude: Mexico City 2,240 m, Guadalajara 1,566 m); knockout matches can go to extra time/pens but **betting markets settle on 90 minutes** — the model predicts 90-minute outcomes everywhere.

---

## Repository layout

```
worldcup-model/
├── CLAUDE.md                  # agent operating manual (content below)
├── STATUS.md                  # current phase, next task, blockers — single source of truth
├── CHANGELOG.md               # Keep-a-Changelog format, newest on top
├── DECISIONS.md               # ADR-lite: numbered decisions w/ date + rationale
├── README.md                  # human overview + quickstart
├── pyproject.toml             # uv-managed; deps pinned via uv.lock
├── .python-version            # 3.12
├── Makefile                   # make test / lint / predict / settle / clv
├── docs/
│   ├── DATA.md                # every source: URL, schema, refresh cadence, failure modes
│   ├── MODEL.md               # model specs, fitted-param versioning, backtest results
│   └── PLAYBOOK.md            # daily tournament routine, step by step
├── config/
│   ├── teams.yaml             # canonical team registry + per-source aliases
│   ├── referees.yaml          # ref name aliases (FBref vs FIFA spellings)
│   └── settings.yaml          # bankroll, unit %, edge threshold, decay rate
├── data/
│   ├── raw/                   # immutable downloads/scrapes (git-ignored, cached forever)
│   ├── processed/             # parquet outputs of pipelines (git-ignored, rebuildable)
│   └── manual/                # hand-entered files (lines.csv, results_patch.csv) — IN git
├── ledger/
│   └── bets.csv               # append-only bet log — IN git
├── src/wc26/
│   ├── data/                  # ingest: results, elo, fbref stats, refs
│   ├── models/                # goal_engine, corners, cards, team_totals
│   ├── markets/               # odds parsing, de-vig, edge calc, staking
│   ├── backtest/              # walk-forward harness, metrics, calibration
│   └── cli.py                 # single Typer entry point: `wc26 <command>`
└── tests/
    ├── fixtures/              # tiny frozen CSVs/HTML for deterministic tests
    └── ...
```

---

## CLAUDE.md (write this file verbatim in Phase 0)

```markdown
# WC26 Edge Model

Python pipeline that prices World Cup 2026 match props (corners, cards, team
totals) and flags +EV bets vs. manually entered sportsbook lines. Real money,
small stakes. Success = positive CLV and calibration, not short-term P&L.

## Session protocol (do this first, every session)
1. Read STATUS.md — it states the current phase, the next task, and blockers.
2. Do the smallest next task. Don't start a new phase if the current one has
   unmet acceptance criteria.
3. Before ending: update STATUS.md, add a CHANGELOG.md entry, log any
   non-obvious choice in DECISIONS.md, run `make test`.
A task is not done until tests pass and docs reflect it.

## Commands
- `uv sync`            install (uv manages everything; never pip install)
- `make test`          pytest (must pass before any commit)
- `make lint`          ruff check + format
- `wc26 predict --date YYYY-MM-DD`   model probabilities for that day's matches
- `wc26 edges`         compare model vs data/manual/lines.csv, print +EV bets
- `wc26 log-bet` / `wc26 settle` / `wc26 clv-report`   ledger ops
- `wc26 add-result`    append a finished match (Kaggle lags during tournament)
- `wc26 refit`         re-fit models on latest data, version the params
- `wc26 sim` / `wc26 rankings [--diff]`   Monte Carlo of remaining tournament →
  per-team advancement/champion probabilities, recalculated from live results

## Architecture (data flows one way)
raw sources → src/wc26/data (ingest, normalize) → data/processed/*.parquet
→ src/wc26/models (fit/predict) → src/wc26/markets (de-vig, edges, stakes)
→ cli. Models never read raw data; markets never compute model probabilities.

## Domain invariants — violating these silently loses money
- ALL probabilities are for the 90-minute result. Knockout games can draw.
- ALL odds are stored as decimal. Parse American/fractional at the boundary.
- NEVER compare model probability to raw implied probability: de-vig first
  (multiplicative method; see DECISIONS.md #odds-devig).
- NEVER fit or evaluate on data from on/after the match date (leakage). The
  backtest harness enforces walk-forward; don't bypass it.
- Team names: only canonical IDs from config/teams.yaml pass module
  boundaries. Unknown name = raise, never fuzzy-guess. Same for referees.
- Times: store UTC; venue-local only at the CLI display layer. (3 host
  countries, 4 time zones.)
- ledger/bets.csv is append-only. Corrections = new correcting row, never
  edits. Stakes are flat units from config/settings.yaml; no Kelly until
  CLV > 0 over 50+ bets.
- Neutral-venue model: home advantage applies ONLY to USA/Mexico/Canada.
  Altitude flag for Mexico City/Guadalajara venues.
- Small-data humility: international teams play ~10 matches/yr. Shrink
  team parameters toward the mean (Elo-anchored prior); a debutant's rating
  is its Elo prior, not its 3-match sample.

## Code practices
- Python 3.12, typed (mypy --strict on src/), ruff for lint+format.
- pandas + pandera schemas at every pipeline boundary: every function that
  returns a DataFrame validates it. Schema drift must fail loudly at ingest,
  not corrupt a prediction silently.
- Use penaltyblog for Dixon-Coles fits and odds conversion — never hand-roll
  Poisson likelihoods or de-vig math.
- Scraping: only via soccerdata's cached interface; respect FBref's ~1 req/6s;
  raw responses are cached in data/raw forever and never re-fetched.
- Every fitted model is saved with: fit date, git SHA, data cutoff date, and
  params (data/processed/models/). Predictions record which model version
  produced them.
- Randomness: fixed seed (settings.yaml) for any simulation; fits must be
  deterministic.
- Tests: every model gets (a) golden tests on frozen fixtures and (b) a
  calibration test on the backtest sample with explicit thresholds. Pure
  functions over classes; no I/O inside model code.
- No new dependencies without a DECISIONS.md entry.

## Gotchas already hit or anticipated (check before "fixing")
- Kaggle results CSV lags days behind live results → use `wc26 add-result`,
  patches live in data/manual/results_patch.csv (in git).
- FBref international match reports are sparse for friendlies; corners/cards
  training data comes from majors + qualifiers (2018→). Don't silently train
  on club data.
- Referee assignments appear ~2 days before kickoff; cards predictions
  without a known ref must say so and widen uncertainty.
- penaltyblog's Dixon-Coles defaults assume club football's home advantage —
  we fit with a neutral-venue flag instead.
```

---

## Phased build (each phase = working software + updated docs)

Every phase ends with: `make test` green, `STATUS.md` updated, `CHANGELOG.md` entry, acceptance criteria checked off. Phases are sized so one agent session can complete one (Phase 2 may take two).

### Phase 0 — Scaffold (no model code)
1. `git init` repo at `/Users/robert/worldcup-model`; `uv init`, Python 3.12 pin; deps: `penaltyblog`, `pandas`, `pandera`, `soccerdata`, `typer`, `pyyaml`, `pytest`, `ruff`, `mypy` (all pinned via `uv.lock`).
2. Write all five docs: CLAUDE.md (verbatim above), STATUS.md (template: Phase / Next task / Blockers / Last session summary), CHANGELOG.md (`## [Unreleased]` + Keep-a-Changelog header), DECISIONS.md (seed with D001 repo layout, D002 uv, D003 penaltyblog, D004 90-min settlement, D005 multiplicative de-vig, D006 append-only ledger), docs/DATA.md skeleton.
3. Makefile, pre-commit (ruff + pytest-on-push), `tests/test_smoke.py`, empty package importable, `wc26 --help` works.
4. `config/settings.yaml` with bankroll, `unit_pct: 0.015`, `edge_threshold: 0.05`, `seed`, `dixon_coles_decay`.

**Accept**: fresh clone → `uv sync && make test` green; `wc26 --help` lists stub commands; all docs exist.

### Phase 1 — Data layer
1. **Team registry**: build `config/teams.yaml` for all 48 qualified teams + ~150 historical opponents — canonical ID + aliases per source (kaggle/fbref/elo/book). Loader raises `UnknownTeamError` on miss. This is the #1 cross-source breakage point; do it first.
2. **Results ingest**: download Kaggle CSV into `data/raw/`, normalize → `processed/results.parquet` (pandera schema: date UTC, home/away canonical ID, score, `neutral`, tournament tier). Merge `data/manual/results_patch.csv` on top, dedupe by (date, teams).
3. **Own Elo**: compute Elo from the results history (K varies by tournament tier, goal-diff multiplier, neutral handling). Snapshot Elo *as of any date* (needed for leak-free backtests). Validate: today's top 10 roughly matches eloratings.net (document tolerance in test).
4. **FBref match stats**: via soccerdata, scrape match-level corners/cards/fouls/shots + referee for WC 2018, WC 2022, Euro 2024, Copa 2024, continental qualifiers 2023→2026, and WC 2026 matches played so far. Cache raw permanently. → `processed/match_stats.parquet`. Build `config/referees.yaml` + ref career card-rate table.
5. **`wc26 add-result`**: interactive append of score + corners + cards + ref for tournament matches (this is the daily data path during the tournament — assume Kaggle/FBref lag).
5b. **Tournament schedule**: `data/manual/schedule.csv` (in git) — all 104 WC 2026 matches: match number, stage, group, teams (canonical IDs; knockout slots as placeholders like `1A`, `3rd-B/E/F`), venue, altitude flag, kickoff UTC. Entered once from the official fixture list; this drives `predict --date`, the group-state tracker, and the tournament simulator.
6. Fill in docs/DATA.md: per source — exact URL, schema, refresh trigger, known failure modes, what to do when it breaks.

**Accept**: `wc26 data status` prints row counts + freshness per table; re-running ingest is idempotent; unknown team names in any source raise with a fix-it hint (add alias to teams.yaml); Elo snapshot test passes; ≥600 matches with corners+cards in match_stats.

### Phase 2 — Goal engine + backtest harness (build together; the harness is how we know the engine works)
1. **Engine**: penaltyblog Dixon-Coles with time-decay weighting, fitted on internationals (tier-weighted: WC > continental > qualifier > friendly), neutral-venue flag, Elo-anchored shrinkage for sparse teams (document the exact blend in docs/MODEL.md). Output: full correct-score matrix → 1X2, team totals, match totals.
2. **Walk-forward backtest harness** (generic — prop models reuse it): for each historical match, fit only on data before that date (monthly refit grid to keep it fast), predict, score. Metrics: log-loss & Brier vs. two baselines — (a) Elo-only, (b) de-vigged market closing odds (1X2 closing odds for WC 2018/2022 + Euro 2024 are free from football-data.co.uk-style archives; document the actual source used in DATA.md). Calibration plot artifacts saved to docs/.
3. **Reality gates** (hard test assertions): backtested log-loss beats Elo-only baseline; is within a documented margin of the market baseline (we do NOT expect to beat the 1X2 market — if we "do", hunt the leak); model's WC26 1X2 for the next match day is within sanity distance of current market odds.
4. `wc26 refit` + model-version persistence; `wc26 predict --date` prints 1X2 + totals probabilities with model version.

**Accept**: backtest report committed to docs/MODEL.md with the three gates green; predictions for tomorrow's real fixtures print in <10 s from cached data.

### Phase 3 — Prop models (the actual product)
1. **Team totals**: direct marginals of the score matrix (over/under any line via the correct-score distribution). Nearly free; ship first.
2. **Corners**: negative-binomial regression (statsmodels) on match expected-goals gap, combined attack proxies (shots from match_stats), favorite-status, stage (group MD1/2/3 vs knockout), per-team corner rates shrunk to mean. Predict total-corners distribution → P(over/under) for any line.
3. **Cards**: negative-binomial / Poisson with referee career card rate (biggest single feature), match stakes (elimination risk both sides — derived from group state), rivalry/derby flag (small manual list), team foul rates, knockout flag. Ref unknown → fall back to tournament-average ref with widened variance, flagged in output.
4. Run all three through the Phase 2 walk-forward harness on 2018→2024 majors. Gates: each model beats its naive baseline (historical tournament mean for that stat) on log-loss; calibration slope in [0.8, 1.2] documented in docs/MODEL.md. Where historical prop closing lines can be sampled (OddsPortal archive, manual sample of ~50 matches is enough), record model-vs-line hit rate honestly.

**Accept**: `wc26 predict` adds corners/cards/team-totals distributions with explicit uncertainty; backtest section in docs/MODEL.md; cards output clearly labels ref-known vs ref-unknown.

### Phase 4 — Market layer: edges, ledger, CLV
1. **Line entry**: `data/manual/lines.csv` (match, market, line, side, decimal/American odds, book, timestamp). `wc26 edges` parses, de-vigs two-way markets, compares to model, prints table sorted by edge, flags edge ≥ threshold, recommends flat stake from settings. Hard guard: refuses lines for matches the model hasn't predicted, stale lines (>24 h), unknown teams.
2. **Ledger**: `wc26 log-bet` appends (timestamp UTC, match, market, line, odds taken, stake, model prob, model version, edge) to `ledger/bets.csv`. `wc26 settle` records result + closing line (entered manually at kickoff) and computes CLV per bet. `wc26 clv-report`: cumulative CLV, ROI, calibration of bet-on probabilities, by market. Append-only enforced by schema check in tests.
3. **Odds API integration (optional, budgeted)**: one call per match day for h2h sanity check, ≤150 credits/mo, hard budget counter persisted so we never burn the tier.
4. docs/PLAYBOOK.md: the exact daily routine (below) — written for the user AND for an agent running it.

**Accept**: full dry-run on one real match day — enter real lines, get edge report, log a paper bet, settle it next day, CLV report renders. Ledger schema test green.

### Phase 5 — Tournament simulator & country rankings
1. **Group-stage state tracker**: from schedule.csv + results, compute live standings per group with full FIFA tiebreakers (points → GD → goals scored → head-to-head among tied → fair-play points if available → random for drawing of lots) and elimination scenarios per team (also drives the cards "stakes" feature and spots MD3 dead rubbers — historically the softest lines).
2. **Monte Carlo simulator** (`wc26 sim`, default 20k runs, seeded): simulate every remaining match from the goal engine's score matrix; completed matches are taken as fact. Implements the full 2026 format: 12 groups, top 2 + 8 best third-placed (with FIFA's third-place bracket-allocation table), round of 32 → final. Knockout 90-min draws resolve via extra-time/penalty model (strength-weighted conditional on the draw; document the exact rule in DECISIONS.md).
3. **Rankings output** (`wc26 rankings`): per-team table for all 48 — P(advance), P(R16), P(QF), P(SF), P(final), P(champion), expected finishing position (rank by expected exit round, tie-broken by P(champion)). Re-running after `add-result` automatically recalculates from current standings — that's the "recalculate" requirement; no extra state needed beyond results. Saved as a dated snapshot in `data/processed/rankings/` so movement between match days is diffable (`wc26 rankings --diff` vs previous snapshot).
4. **Validation**: simulator gates as tests — group-stage probabilities for an already-decided group collapse to certainty; all 48 teams' P(champion) sums to 1; deterministic under fixed seed; tiebreaker unit tests on constructed fixtures (incl. three-way ties).
5. Futures sanity check: never bet futures unless `wc26 rankings` and CLV tracking are both healthy; the simulator exists primarily for rankings + knockout context, not betting volume.

**Accept**: `wc26 rankings` runs in <60 s, recalculates correctly after adding a result (spot-check: eliminated team → 0% everywhere), snapshot diffing works, gates green.

### Phase 6 — Tournament ops (rest of group stage + knockouts)
1. Daily routine per PLAYBOOK.md: `add-result` for yesterday → `refit` (weekly or after each match day of own-group data; decide and record in DECISIONS.md) → `predict` → `rankings` → enter lines → `edges` → bet/log → `settle` prior bets.
2. After group stage (July 3): recalibration checkpoint — compare predicted vs. realized for ~72 matches, adjust shrinkage/decay, version the refit, note in CHANGELOG + MODEL.md. Knockout flag flips on for cards model; knockout bracket in the simulator switches from projected to actual.

**Accept**: routine takes <15 min/day; ≥50 logged bets (paper + real) by knockouts with CLV report; post-group recalibration documented.

---

## Risk register (anticipated breakage → built-in guard)

| Risk | Guard |
|---|---|
| Team/ref name drift across sources mid-tournament | Canonical registry, hard `UnknownTeamError`, alias fix is a 1-line yaml edit |
| FBref layout change / scrape ban | Permanent raw cache, pinned soccerdata, `add-result` manual path keeps the tournament loop alive without any scraping |
| Kaggle CSV lag during tournament | `results_patch.csv` in git is authoritative for recent matches |
| Backtest leakage (the silent killer) | Walk-forward harness is the only eval path; as-of-date Elo; reality gate that "beating the market in backtest" is treated as a bug until proven otherwise |
| Odds-format mistakes (American −110 vs decimal) | Decimal-only internals, parser at boundary with tests for negative American odds |
| Knockout draw forgotten (90-min settlement) | Invariant in CLAUDE.md + test asserting knockout 1X2 probs include draw |
| Schema drift corrupting silently | pandera validation at every pipeline boundary |
| Ledger corruption / revisionism | Append-only convention + schema test; file in git so history is auditable |
| Non-reproducible fits | Seeds in config, model versions stamped with git SHA + data cutoff |
| Dependency rot | uv.lock pinned; new deps require DECISIONS.md entry |
| Overbetting on model noise | Flat stakes + 5% edge floor + no-Kelly rule encoded in settings and CLAUDE.md |
| Agent context loss between sessions | Session protocol in CLAUDE.md; STATUS.md as single source of truth; CHANGELOG discipline |

## Verification (end-to-end, per phase and final)

- Every phase: `make test && make lint` green; fresh-clone smoke (`uv sync` → CLI runs).
- Phase 2/3: backtest gates are *tests*, not judgment calls — they fail CI if calibration regresses after a refit.
- Final acceptance: one complete real match-day cycle (predict → lines → edges → log → settle → clv-report) executed against live WC 2026 fixtures with real book lines, results matching manual spot-checks of the math (one hand-computed de-vig + edge in tests/fixtures).

## Execution notes

- Start at Phase 0 immediately; Phases 0–1 are realistic for the first session, Phase 2 next. First real edge reports are plausible within ~3–4 sessions, rankings one session later — still inside the group stage (ends July 3), leaving 40+ matches.
- The current cwd is an unrelated iOS repo — all work happens in the new `/Users/robert/worldcup-model` repo.
