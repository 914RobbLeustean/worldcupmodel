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
