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
