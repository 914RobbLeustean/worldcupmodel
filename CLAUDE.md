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
