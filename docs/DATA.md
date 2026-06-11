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

## ESPN match stats (corners, cards, fouls, shots, possession, referee)
- Replaced FBref (Cloudflare-blocked) — see DECISIONS D011.
- Endpoints: site.api.espn.com .../soccer/{league}/scoreboard?dates=YYYYMMDD
  and .../summary?event={id}. League codes: fifa.world, uefa.euro,
  conmebol.america. No auth required.
- Coverage: WC 2018, WC 2022, Euro 2024, Copa América 2024, WC 2026 live.
  Qualifier coverage exists (fifa.worldq.*) but stats are spottier — add only
  if Phase 3 needs more sample.
- Refresh: `wc26 data scrape` — fully cached (finished matches/days never
  re-fetched), 1.2 s pause per request, safe to interrupt/resume.
- Failure modes: undocumented API can change shape (parsers raise on unknown
  final-status enums and unmatched boxscore teams rather than guess); ESPN
  dates are UTC kickoff dates (join with ±1 day tolerance, D013); knockout
  stats include extra time (`extra_time` flag, D012).
- Fallback: `wc26 add-result` manual entry — the tournament loop never
  depends on the API being up.
- Known gaps: referees missing for WC 2018 (ESPN has no officials data that
  far back; 2022+ is 100%). Optional backfill from Wikipedia if the cards
  model wants the extra 64 training rows. Qualifier legs (fifa.worldq.*) are
  an optional Phase 3 extension if 211 majors prove too small a sample.
- Status: INGESTED 2026-06-12 → match_stats.parquet (211 matches: WC18/22 64
  each, Euro24 51, Copa24 32; corners 100%, refs 70%) + referees.parquet (51
  refs). Verified: extra-time counts exact for all four tournaments (5 each),
  WC18/WC22 finals spot-checked.

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
