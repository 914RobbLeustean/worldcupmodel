# Daily tournament playbook

> The exact match-day routine, for the user or an agent. Finalized in Phase 4.
> Every command below is `uv run wc26 ...` (or plain `wc26 ...` inside the venv).
> Total time: ~10 minutes.

## 1. Morning — data + model (~3 min, agent-runnable)

```
wc26 data scrape --tournament wc2026   # yesterday's finals from ESPN (cached, resumable)
wc26 data sync                         # write finished results into the patch + re-ingest
wc26 data status                       # confirm freshness (results/fixtures/match_stats)
wc26 refit                             # fold new results into all models, version params
                                       # cadence: EVERY completed match day (D025) —
                                       # never skip to "save" a refit, never refit twice
                                       # for the same data state
wc26 backtest && uv run pytest         # re-check ALL reality gates after the refit (~2 min)
wc26 predict                           # today's probabilities (1X2 + props)
wc26 rankings --diff                   # advancement snapshot + movement vs yesterday (~6 s)
wc26 sim                               # group standings, statuses, MD3 dead rubbers
```

**Near each kickoff — capture the closing odds (D033, needs ODDS_API_KEY):**

```
wc26 snapshot-odds                     # 1X2 + match totals for all upcoming
                                       # matches -> data/odds_snapshots.csv
                                       # (2 credits; 400/mo cap, D031)
```

Run it as late as you can before a kickoff (cron it if you have a server):
the latest pre-kickoff snapshot per match is its CLOSING anchor — it removes
the need to be awake to hand-capture, and auto-anchors pricing for any match
you didn't type a 1X2 for. The free tier serves current (near-closing) odds,
a closing proxy (D015).

Failure modes:
- ESPN down/wrong → `wc26 add-result` (manual score/corners/cards/ref entry).
- "Unknown team name X" → add the spelling to `aliases` in config/teams.yaml.
  Fix the alias; NEVER loosen the strict resolution.
- Referee announced (~2 days out) → add a row to
  data/manual/ref_assignments.csv (`date,home_id,away_id,referee`, ESPN
  spelling) so cards output flips to ref-known. (Reference only — D021.)

## 2. Settle yesterday's bets

The result is read from the results table automatically; you only supply the
CLOSING line. Three ways, in order of preference (D034):

```
# A) you captured the book's prop close (best):
wc26 settle B0001 --closing-over 1.85 --closing-under 1.95

# B) you have the closing 1X2 but not the prop close:
wc26 settle B0001 --anchor-1x2 2.12/3.30/4.09

# C) nothing captured — use the odds snapshot automatically (D033):
wc26 settle B0001          # uses the latest pre-kickoff snapshot for the match
```

If you ran `wc26 snapshot-odds` near kickoff (step 1), option C needs no
input at all. The CLV source is recorded in the ledger note
(`clv_src=...`). Snapshot/1X2 CLV is a consensus close (not Superbet's own —
D033), so it's a slightly conservative proxy; a captured prop close (A) is
the most precise.

- The result is read from the results table automatically.
- **Extra time (knockouts):** ALL bets settle on the 90-minute score (D004),
  but stored knockout scores include ET (D012) — `settle` detects this and
  refuses; re-run with `--goals <the team's 90' goal count>`.
- Mis-entered a settlement? Corrections are NEW rows (the ledger is
  append-only, D006): re-settling a settled bet is blocked, so append a
  correcting row manually with the same bet_id — never edit existing rows.

## 3. Enter today's lines AND the 1X2 anchor (user, from the sportsbook)

Pricing is market-anchored (D028): a team total is priced off the book's
own 1X2, so you enter TWO files per match. The 1X2 anchor is required — but
if you ran `wc26 snapshot-odds` (step 1), the snapshot is used automatically
when you skip anchors.csv (shown as src=snap / BET* in `edges`). Entering the
book's own 1X2 is still better (it measures THAT book's prop-vs-1X2
inconsistency); the snapshot is the fallback.

**3a. `data/manual/anchors.csv`** — the book's 1X2 (one row per match):

```csv
ts_utc,match,home_odds,draw_odds,away_odds,book
2026-06-13T17:00:00,USA v Paraguay,2.12,3.30,4.09,superbet
```

- `home_odds` is for the FIRST team you type in `match` (typed either way;
  it's mapped to fixture orientation automatically).
- one row per (match, book); enter the SAME book you'll quote the props from
  so the edge measures that book's prop-vs-1X2 inconsistency.

**3b. `data/manual/lines.csv`** — the team-total quotes, one row per quoted
side (both sides required, that's what de-vig needs):

```csv
ts_utc,match,market,line,side,odds,book
2026-06-13T17:00:00,USA v Paraguay,team_total:Paraguay,1.5,over,3.90,superbet
2026-06-13T17:00:00,USA v Paraguay,team_total:Paraguay,1.5,under,1.23,superbet
```

- `ts_utc`: when you read the quote (UTC). Quotes >24 h old are refused.
- `match`: `<home> v <away>` — any spelling from config/teams.yaml.
- `market`: `team_total:<team>` is the ONLY priceable market (match totals
  D019, corners/cards D021 are quarantined; entering them is refused).
- `line`: half-goal lines only (1.5, not 2).
- `odds`: decimal (`1.91`) or American (`-110`, `+120`) — sign required for
  American.
- `book`: same market at two books = two row pairs with different `book`.

## 4. Edges → bet → log (~2 min)

```
wc26 edges      # table sorted by edge; BET rows are >= the 5% threshold
```

Reading the table: `anchor` = P(side) implied by the book's 1X2 (the pricing
prob), `eng` = engine grid P(side) (context only — D028 retired it as the
pricing source), `fair` = de-vigged prob of the recommended side from the
prop quote, `edge` = anchor − fair, `ev` = expected profit per unit at the
quoted odds. Only bet `BET` rows; `· NO ANCHOR` rows need a 1X2 in
anchors.csv first; `BET*` means the anchor came from a different book than
the quote. A positive edge with negative `ev` means the vig eats the edge.

For every bet actually placed (at the book, or on paper), log it
IMMEDIATELY with the odds you actually got:

```
wc26 log-bet --match "USA v Paraguay" --team USA --line 1.5 --side under --odds 1.52
```

Money rules (non-negotiable, enforced in code): flat 1.5% units, 5% edge
floor, no Kelly until CLV > 0 over 50+ settled bets, no futures without a
healthy simulator + CLV.

## 5. Weekly — review

```
wc26 clv-report   # cumulative CLV, ROI, win rate vs model_p, by market
```

- CLV is the success metric, not P&L. If mean CLV ≤ 0 after 50 settled
  bets: STOP betting, review (CLAUDE.md invariant).
- After the group stage: Phase 6 recalibration checkpoint (re-gate match
  totals + corners/cards, D019/D021).

## Agent notes

- Steps 1–2 are fully agent-runnable at session start; step 3 needs the
  user's book; steps 4–5 are agent-runnable once lines.csv is filled.
- All guards are hard errors by design (stale lines, unknown teams,
  quarantined markets, unpredicted matches, one-sided quotes). Fix the
  input, never the guard.
- Before ending a session: `make test && make lint`, update STATUS.md,
  CHANGELOG.md, commit (ledger + lines.csv are in git on purpose).
