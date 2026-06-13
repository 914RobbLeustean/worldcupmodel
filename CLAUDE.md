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
- `make lint`          ruff check + format check + mypy
- `wc26 predict --date YYYY-MM-DD`   model probabilities for that day's matches
- `wc26 edges`         price team totals MARKET-ANCHORED (D028/D032): from the
  book's 1X2 in data/manual/anchors.csv (or the odds snapshot), NOT the engine
  grid; compare to lines.csv and print +EV bets. No anchor = unpriceable.
- `wc26 snapshot-odds`  capture consensus 1X2 + match totals to
  data/odds_snapshots.csv (D033; needs ODDS_API_KEY) — closing anchor + the
  auto-anchor fallback for edges/log-bet. Run near each kickoff.
- `wc26 log-bet` / `wc26 settle` / `wc26 clv-report`   ledger ops (settle
  auto-derives CLV from the snapshot/1X2 anchor if no prop close given, D034)
- `wc26 add-result`    append a finished match (Kaggle lags during tournament)
- `wc26 refit`         re-fit models on latest data, version the params
- `wc26 backtest`      walk-forward backtest vs Elo + market baselines;
  refreshes the artifacts the reality-gate tests assert on
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
  (multiplicative method; see DECISIONS.md D005).
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
- Match stats come from ESPN's JSON API via src/wc26/data/espn.py (D011 —
  FBref is Cloudflare-blocked). Keep the 1.2 s request pause; finished
  matches/days are cached in data/raw/espn forever and never re-fetched.
- Every fitted model is saved with: fit date, git SHA, data cutoff date, and
  params (data/processed/models/). Predictions record which model version
  produced them.
- Randomness: fixed seed (settings.yaml) for any simulation; fits must be
  deterministic.
- Tests: every model gets (a) golden tests on frozen fixtures and (b) a
  calibration test on the backtest sample with explicit thresholds. Pure
  functions over classes; no I/O inside model code.
- No new dependencies without a DECISIONS.md entry.

## Gotchas already hit (check before "fixing")
- Upstream results CSV lags live results → `wc26 add-result` or `wc26 data
  scrape` (ESPN picks up finals same day); patches live in data/manual/.
- EXTRA TIME (D012): knockout scores/stats in BOTH sources include ET. Use
  the `extra_time` flag; never train 90'-market models on flagged rows as-is.
- Dates differ across sources (D013): ESPN uses UTC kickoff dates, results
  CSV uses local dates. Cross-source joins must match team pair ±1 day.
- FBref is Cloudflare-blocked (403 to plain HTTP, needs Chrome via
  soccerdata) — don't re-attempt it casually; ESPN is the source (D011).
- Corners/cards training data = majors 2018→ plus UEFA WC qualifiers (D020;
  the ONLY confederation with ESPN team stats — checked). Qualifier rows are
  training-only behind a level dummy. Don't silently train on club data.
- Referee assignments appear ~2 days before kickoff; cards predictions
  without a known ref must say so and widen uncertainty.
- penaltyblog's Dixon-Coles defaults assume club football's home advantage —
  we fit with a neutral-venue flag instead.
