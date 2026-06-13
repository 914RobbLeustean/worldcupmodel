# Improvement backlog — from the 2026-06-12 strategic review

> Prioritized by (expected edge gain ÷ effort+risk). Each item states its
> effect class — **[edge]** (more CLV per bet), **[accuracy]** (better
> calibration/log-loss), or **[both]** — its validation path, and who can do
> it (AGENT = an AI session alone; HUMAN = needs the user's hands, accounts,
> or money). Statuses: TODO / IN PROGRESS / DONE / BLOCKED(on what).
>
> Context: the 2026-06-12 review found the pipeline's one structural flaw is
> that it never uses the market as a pricing input despite its own backtest
> showing the market beats the engine (0.9706 vs 0.9952 log-loss), so
> `edge = model_p − fair_p` with threshold 0.05 mostly selects
> maximal-disagreement matches (mean model-market diff is 0.074). B0002/B0003
> (both −5% CLV, close ratified the book not the model) are n=2 but
> mechanism-consistent.

## NOW (before/while the group stage runs)

1. **Market-anchored team-total pricing** — [both] — **DONE 2026-06-13: experiment PASS (D028) + live wiring in edges/log-bet (D032). Betting un-paused. User now enters the book's 1X2 in anchors.csv per match.**
   - Hypothesis: team totals priced from a DC grid whose lambdas are solved to
     reproduce the de-vigged market 1X2 beat the engine's own grid
     out-of-sample; live edges then measure intra-book inconsistency, not
     model-vs-market disagreement.
   - Validation: walk-forward-clean experiment on the existing 191-row props
     eval joined to market_odds.parquet (D015). Decision rule pre-registered in
     D028. Live wiring (book 1X2/total quotes in lines.csv → anchored edges)
     only if the experiment passes — that part is BLOCKED(user enters the
     book's 1X2 + match-total quotes alongside prop lines; +2 rows/match).
   - Owner: AGENT (experiment + wiring), HUMAN (2 extra quote rows per match).

2. **Shrink model_p toward fair_p before edge / two-key rule** — [edge] — **DONE 2026-06-13: w*=0.00 (D028) — superseded by #1's pivot; new bets paused until #1 wiring lands**
   - Fit w minimizing log-loss of `w·engine + (1−w)·market` on the 211-match
     1X2 backtest; that w is the honest weight the model's opinion deserves
     against a quote. Policy change to `wc26 edges` follows the verdict of #1
     (anchored pricing supersedes shrinkage if adopted; else shrinkage applies).
   - Owner: AGENT.

3. **Historical prop-line sample (the unfulfilled PLAN 3.4 item)** — [edge] — **IN PROGRESS: user collects manually (chosen 2026-06-13); agent builds the eval script once rows land**
   - ~50–100 team-total/corners/cards closing lines for WC22/Euro24 matches
     from OddsPortal archives → measures (a) how soft these books actually are
     (the project's founding premise, currently unmeasured), (b) a market
     baseline for team totals (the live model has only ever beaten a no-skill
     naive), (c) a data-derived edge_threshold.
   - Owner: HUMAN (~2–4 h manual collection into a CSV template the agent
     provides), or AGENT-with-Chrome if the user connects the browser
     extension. Eval script: AGENT.
   - Template ready: data/manual/historical_prop_lines.csv. How to fill:
     OddsPortal → tournament archive (WC 2022, Euro 2024) → match page →
     "Over/Under" / "Corners" / "Cards" tabs → use the CLOSING odds (the
     last value, shown on hover), average across books or one named book —
     set `book` accordingly and `is_closing` TRUE. market is one of
     `team_total:home`, `team_total:away`, `match_total`, `corners`,
     `cards`; decimal odds; one row per line per match. ~50 matches with
     the team-total markets is the minimum useful sample; corners/cards
     rows are bonus. Team names as shown on the site — the eval script
     resolves aliases.

4. **WC scoring-environment offset in the engine** — [accuracy, modest edge] — **DONE 2026-06-13 (D035): built + walk-forward validated (improves WC 1X2/team/match log-loss, holds gates, doesn't fix slope). Default OFF — pricing-irrelevant post-pivot; activation at the July-3 recalibration.**
   - D019 documented the engine under-predicting WC scoring (2.20 vs 2.66
     goals/match, favorite-side) via anchor shrinkage; fix = a finals
     environment offset fit walk-forward on pre-cutoff WC rows. Validated by
     the existing harness + all gates; pre-register that match totals stay
     quarantined unless the O2.5 slope actually enters [0.8, 1.2].
   - Owner: AGENT (~1 session).

5. **Line shopping: 1–2 more books** — [edge] — **DEFERRED by user (2026-06-13): Superbet-only for now; revisit after anchored pricing is live**
   - Open/fund accounts at 1–2 more Romanian books (e.g. Betano, Unibet RO,
     MaxBet); type their team-total quotes into lines.csv (the `book` column
     already exists; zero code). Best-of-N quotes is plausibly worth more EV
     than any model change on this list.

6. **Automated closing-line backup** — [protects the success metric] — **DONE 2026-06-13 (D033): `wc26 snapshot-odds` captures 1X2+totals to data/odds_snapshots.csv (append-only, in git); auto-anchors edges/log-bet when no anchors.csv row. Run near each kickoff (cron-able). Needs ODDS_API_KEY.**
   - STATUS.md: "Closing lines must be captured at kickoff or CLV is lost."
     Snapshot the already-ingested BetExplorer odds at kickoff as a fallback
     closing proxy (1X2/match totals; the prop close itself stays manual).
     Optionally raise the Odds API budget (D007) for h2h+totals closing
     snapshots — needs a DECISIONS entry.
   - Owner: AGENT (BetExplorer snapshot), HUMAN (decision on Odds API budget).

7. **Correlation guard in bet logging** — [protects the CLV gate + bankroll] — **DONE 2026-06-13 (D029)**
   - Refuse a second OPEN bet on the same (match, market): B0002+B0003 and
     B0004+B0005 are nested same-team totals that win/lose together; the
     50-bet CLV gate assumes rough independence.
   - Owner: AGENT.

8. **Re-derive edge_threshold from data** — [edge] — **TODO, BLOCKED(#3)**
   - 0.05 was a Phase-0 guess; it is below the measured mean model-market
     disagreement (0.074), so it filters model opinion, not book error.
     Re-set from the #3 sample's measured book error distribution.

## JULY-3 checkpoint (needs WC26 group-stage outcomes — keep calendar-gated)

9. **Corners/cards re-gate on ~72 WC26 matches** (D021, STATUS step 3) —
   pre-registered expectation (see D030): at n≈70 even a true 2–4% improvement
   is hard to certify; a second failure is the likely, acceptable outcome.
10. **Cards: referee club-career priors** — [accuracy→maybe edge] — only if
    the re-gate's ref-known slice shows a near-miss. Sourcing: multi-league
    ref card rates (scrape or paid feed) — the one place paid data has a
    plausible gate-clearing mechanism.
11. **Squad-value covariate in the Elo anchor (Transfermarkt)** — [accuracy] —
    requires HISTORICAL as-of squad values (2018/2022/2024 cutoffs) for
    leak-free validation, else unshippable. Partially redundant with #1.
12. **Knockout-stage stakes features + bracket flip** (existing STATUS items).

## Small fixes (found in use)

14. **clv-report should split paper vs real money** — [reporting] —
    **DONE 2026-06-13**: real money reports on a "TOTAL (real)" line, paper is
    excluded. Real CLV -12.4% on 4 bets.
15. **Settlement auto-CLV from the odds snapshot** — [data integrity] —
    **DONE 2026-06-13 (D034)**: settle resolves the closing fair prob from
    prop-close -> --anchor-1x2 -> snapshot, on the same rho-consistent grid
    as pricing; CLV source stamped in the note. Originally: The snapshot store (D033) holds a
    near-closing 1X2 per match; `wc26 settle` should auto-derive the anchored
    fair team-total prob from the latest pre-kickoff snapshot (or a
    `--anchor-1x2 H/D/A` flag) and stamp the CLV source, instead of taking a
    manual two-way prop close. This fully automates the CLV loop end to end
    (snapshot -> price -> bet -> settle). AGENT.

## Before ~June 22 (MD3 starts), if capacity allows

13. **Dead-rubber/MD3 lambda adjustment** — [both, small] — the simulator
    already computes secured/eliminated flags (D024) that the pricing engine
    never consumes; PLAN 5.1 calls dead rubbers "historically the softest
    lines". Fit a stakes effect walk-forward on reconstructed historical
    group states. Owner: AGENT (1–2 sessions).

## Explicitly rejected (do not resurrect without new evidence)

- **Model-class rewrite (hierarchical Bayes / GBM ensemble)** — wrong moment:
  3 weeks left, sample-starved props, and gate ii correctly forbids
  pretending to out-predict the 1X2 market. Revisit for the next tournament.
- **Paid event data (Opta/StatsBomb) to rescue corners** — the binding
  constraint is the eval sample (141→~210 matches), not features; the gate
  cannot certify plausible effect sizes at that n regardless of feed.
