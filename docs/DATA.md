# Data source contracts

> One section per source: exact URL, schema, refresh trigger, failure modes,
> and what to do when it breaks. Filled in as each ingest lands (Phase 1).

## International results (martj42, GitHub mirror)
- URL: https://raw.githubusercontent.com/martj42/international_results/master/results.csv
  (same data as the Kaggle dataset, no API key needed — D010)
- What: ~49.5k men's full internationals 1872→present, incl. WC26 fixture rows
  with NA scores; columns: date, home_team, away_team, home_score, away_score,
  tournament, city, country, neutral.
- Refresh: `curl` re-download into data/raw/results.csv, then
  `wc26 data ingest`. Found current through the previous day in June 2026, but
  never rely on it intra-tournament → `wc26 add-result` writes
  data/manual/results_patch.csv which overrides on (date, home, away).
- Failure modes: name spellings differ across sources (config/teams.yaml
  aliases; strict resolution for WC26 rows fails loudly); upstream cadence
  not guaranteed.
- Status: INGESTED 2026-06-11 → results.parquet (49,405 played) +
  fixtures.parquet (72 WC26 group matches, venue + altitude flag).

## Elo ratings (computed in-repo)
- Source: derived from the results table; eloratings.net used only as a
  validation reference (top-10 sanity test with documented tolerance).
- Key property: snapshot **as of any date** for leak-free backtests.
- Formula: eloratings.net-style (home adv +100 unless neutral, goal-diff
  multiplier, K by tier from settings.yaml). `wc26 data elo` prints top N.
- Status: BUILT 2026-06-11; top-12 sanity test in tests/test_results_elo.py.

## FBref match stats (corners, cards, fouls, shots, referee)
- Access: soccerdata's FBref scraper, local permanent cache in data/raw/.
- Coverage target: WC 2018, WC 2022, Euro 2024, Copa América 2024,
  continental qualifiers 2023→2026, WC 2026 as played.
- Rate limit: ~1 request / 6 s. Never bulk re-scrape; cache is forever.
- Failure modes: site layout changes break soccerdata (pinned version);
  scrape ban → fall back to `wc26 add-result` manual entry, the tournament
  loop must never depend on live scraping.
- Status: NOT YET INGESTED.

## Tournament schedule
- Group stage: derived automatically from the results CSV into
  fixtures.parquet (D009) — no manual entry needed.
- Knockout slots + kickoff times: manual entry deferred to Phase 5 when the
  simulator needs the bracket mapping.
- Status: GROUP STAGE DERIVED 2026-06-11.

## Sportsbook lines (manual, in git)
- File: data/manual/lines.csv — typed from the user's book before betting.
- Closing lines entered at kickoff via `wc26 settle` for CLV.
- Status: format defined in Phase 4.

## The Odds API (optional sanity checks only)
- Free tier: 500 credits/month; cost = markets × regions per call.
- Budget: ≤150 credits/mo, enforced by a persisted counter (Phase 4).
- Status: NOT YET INTEGRATED.
