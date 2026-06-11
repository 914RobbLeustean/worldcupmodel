# Data source contracts

> One section per source: exact URL, schema, refresh trigger, failure modes,
> and what to do when it breaks. Filled in as each ingest lands (Phase 1).

## International results (Kaggle, martj42)
- URL: https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017
- What: ~49k men's full internationals 1872→present; `results.csv` with
  date, home_team, away_team, home_score, away_score, tournament, city,
  country, neutral.
- Refresh: one-time download + occasional re-download; **lags days behind live
  results** → recent matches come from data/manual/results_patch.csv instead.
- Failure modes: name spellings differ from FBref/Elo (handled by
  config/teams.yaml); dataset update cadence not guaranteed mid-tournament.
- Status: NOT YET INGESTED.

## Elo ratings (computed in-repo)
- Source: derived from the results table; eloratings.net used only as a
  validation reference (top-10 sanity test with documented tolerance).
- Key property: snapshot **as of any date** for leak-free backtests.
- Status: NOT YET BUILT.

## FBref match stats (corners, cards, fouls, shots, referee)
- Access: soccerdata's FBref scraper, local permanent cache in data/raw/.
- Coverage target: WC 2018, WC 2022, Euro 2024, Copa América 2024,
  continental qualifiers 2023→2026, WC 2026 as played.
- Rate limit: ~1 request / 6 s. Never bulk re-scrape; cache is forever.
- Failure modes: site layout changes break soccerdata (pinned version);
  scrape ban → fall back to `wc26 add-result` manual entry, the tournament
  loop must never depend on live scraping.
- Status: NOT YET INGESTED.

## Tournament schedule (manual, in git)
- File: data/manual/schedule.csv — all 104 matches, canonical team IDs,
  knockout placeholder slots, venue, altitude flag, kickoff UTC.
- Source: official FIFA fixture list, entered once.
- Status: NOT YET ENTERED.

## Sportsbook lines (manual, in git)
- File: data/manual/lines.csv — typed from the user's book before betting.
- Closing lines entered at kickoff via `wc26 settle` for CLV.
- Status: format defined in Phase 4.

## The Odds API (optional sanity checks only)
- Free tier: 500 credits/month; cost = markets × regions per call.
- Budget: ≤150 credits/mo, enforced by a persisted counter (Phase 4).
- Status: NOT YET INTEGRATED.
