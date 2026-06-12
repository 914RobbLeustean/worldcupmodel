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
  far back; 2022+ is 100%) and for the 2022-cycle UEFA qualifiers. Optional
  backfill from Wikipedia if the cards model wants the extra 64 training rows.
- Qualifiers (D020, Phase 3 escape hatch): UEFA World Cup qualifiers ONLY —
  probing (2026-06-12) showed CONMEBOL/AFC/CAF/CONCACAF qualifier summaries
  carry officials but NO team stats on ESPN. Ingested legs: wcq_uefa_2022
  (2021-03→2022-06; stats, no officials) and wcq_uefa_2026 (2025-03→2026-03;
  stats + officials). Tournament label "FIFA World Cup qualification" matches
  the results CSV. Qualifier rows are training-only for the prop models;
  rows with missing stats are dropped, not fatal.
- Status: INGESTED 2026-06-12 → match_stats.parquet (211 majors: WC18/22 64
  each, Euro24 51, Copa24 32; corners 100%, refs 70%; + UEFA WCQ rows per
  D020; + WC26 rows accumulate daily via scrape) + referees.parquet.
  Verified: extra-time counts exact for all four tournaments (5 each),
  WC18/WC22 finals spot-checked.
- Note: `wc26 data scrape --tournament X` merges into the existing table
  (other tournaments are preserved; fixed 2026-06-12).

## Tournament schedule
- Group stage: derived automatically from the results CSV into
  fixtures.parquet (D009) — no manual entry needed.
- Knockout bracket (Phase 5): hand-entered ONCE, in git:
  - data/manual/bracket_2026.yaml — R32 slot pairings, match numbers 73-104,
    dates, venues + countries (knockout host home advantage). Source: FIFA
    World Cup 2026 Regulations (May 2025), art. 12.5-12.11,
    https://digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf
    Dates/venues cross-checked against the FIFA match schedule via
    https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage
  - data/manual/third_place_allocation.csv — FIFA Annex C, all 495
    combinations of eight qualified thirds → R32 slot assignments. Parsed
    programmatically out of the regulations PDF (pp. 80-97) on 2026-06-12,
    then verified: full C(12,8) coverage, every row a permutation of its
    qualified set, every assignment inside the slot's allowed groups, AND a
    495/495 row-for-row match against the independently maintained Wikipedia
    transcription (Template:2026 FIFA World Cup third-place table). Options
    1 and 495 are additionally pinned by hand in tests/test_bracket.py.
- Loaders (src/wc26/sim/bracket.py) re-validate structure on every load;
  group-stage tiebreaker rules come from the same regulations PDF (art. 13,
  D023).
- Failure modes: FIFA reschedules a knockout match (edit the yaml, the
  loader catches structural typos); fixtures.parquet starts carrying
  cross-group knockout rows once upstream adds results — build_group_stage
  raises loudly, knockout facts are a Phase 6 task.
- Status: KNOCKOUT BRACKET ENTERED + VERIFIED 2026-06-12.

## Historical 1X2 market odds (backtest baseline)
- Decision: D015. Output: data/processed/market_odds.parquet (211 rows:
  WC18 64, WC22 64, Euro24 51, Copa24 32), built by
  `wc26.data.market_odds.build_market_odds()` (auto-run by `wc26 backtest`).
- Source 1 — football-data.co.uk: https://www.football-data.co.uk/WorldCup2026.xlsx
  One workbook, per-tournament sheets (WorldCup2022, WorldCup2018, ...).
  Columns used: Date, Home, Away, H-Avg/D-Avg/A-Avg (average odds across
  books). Bonus: HGFT/AGFT are the TRUE 90-minute scores (ET and pens
  recorded separately) — used in tests to verify D012 handling.
- Source 2 — BetExplorer (betexplorer.com): average odds from results pages.
  Group stages come from their AJAX endpoint
  `/res/ajax/league-results.php?par={tournament},{stage},1&show=all&sort=d`
  (par values recorded in market_odds.py; read off each tournament's
  /results/ page). Euro 2024: euro-2024; Copa 2024 lives at /copa-america/
  (no year suffix = latest edition).
- Caching: every raw file under data/raw/odds/ is immutable (finished
  tournaments) and never re-fetched.
- Verification (test-enforced): WC22 final 2.63/3.12/2.84 (football-data) vs
  2.67/3.13/2.86 (BetExplorer); WC18 opener Russia 1.46; Euro24 final Spain
  2.41 — tests/test_market_odds.py.
- LIMITATION: average bookmaker odds collected near kickoff — a closing-line
  proxy, not strict Pinnacle closing odds. Good enough to anchor the "do not
  beat the market" gate; do NOT use for CLV math (Phase 4 enters real
  closing lines manually).
- Failure modes: page/format drift (parsers raise on row-count mismatch:
  128/51/32 expected); BetExplorer team spellings (strict resolution for
  WC26 — fix via config/teams.yaml aliases, e.g. "D.R. Congo").
- Status: INGESTED 2026-06-12.

## WC26 live 1X2 odds (sanity gate + daily reference)
- BetExplorer fixtures page for the live tournament:
  https://www.betexplorer.com/football/world/world-championship-2026/fixtures/
  (note: NOT world-cup-2026 — that URL redirects to the homepage).
- `wc26.data.market_odds.fetch_wc26_live_odds()` snapshots it once per UTC
  day into data/raw/odds/betexplorer_wc26_fixtures_YYYYMMDD.html; rows have
  no date column and join to fixtures by team pair (unique in group stage).
- Used by the gate-iii test (model vs de-vigged market, thresholds in
  settings.yaml `backtest:`) — the test reads the latest snapshot only,
  never the network.
- Status: FIRST SNAPSHOT 2026-06-12 (71 fixtures).

## Sportsbook lines (manual, in git)
- File: data/manual/lines.csv — typed from the user's book before betting.
- Closing lines entered at kickoff via `wc26 settle` for CLV.
- Status: format defined in Phase 4.

## The Odds API (optional sanity checks only)
- Free tier: 500 credits/month; cost = markets × regions per call.
- Budget: ≤150 credits/mo, enforced by a persisted counter (Phase 4).
- Status: NOT YET INTEGRATED.
