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

3. **Historical prop-line sample (the unfulfilled PLAN 3.4 item)** — [edge] — **DONE 2026-06-13 (D036): user collected Euro24+WC22 OddsPortal consensus closes (match-O/U fallback path); ingested to data/manual/historical_prop_lines.csv (688 rows / 115 matches), eval `wc26 eval-prop-lines`. Verdict: consensus match-total close near-unpredictable (O2.5 corr 0.094, log-loss ~ naive) — independently vindicates the D019/D028 match-total quarantine; the 1X2-anchored grid reproduces the independent total close (corr 0.93) — confirms D028 anchoring. Spec retained below for provenance.**

   WHY: measure (a) how well-calibrated soft-book CLOSING prop lines are (the
   project's founding premise — that they're soft — is still UNMEASURED),
   (b) a real market baseline for team totals (the live model has only ever
   beaten a no-skill Poisson naive, never a market price), (c) a data-derived
   `edge_threshold` to replace the Phase-0 guess of 0.05 (backlog #8).

   HONEST CAVEAT: free archives carry the CONSENSUS close, not Superbet's. So
   this measures whether the consensus close is well-calibrated (a sanity
   check on D028 anchoring) and speeds up the threshold — it does NOT measure
   Superbet's own softness. Superbet softness is measured FORWARD by live CLV
   vs the snapshot close (already running). Both are complementary.

   STEP 0 — REALITY CHECK (10 min, do FIRST): historical *team*-total closing
   lines are a niche market free archives often lack. Open oddsportal.com,
   find a finished match (e.g. Spain v England, Euro 2024 final 2024-07-14),
   and check which market tabs exist. Likely present: 1X2, Over/Under (MATCH
   total), BTTS. Maybe absent: individual team totals. Decide the plan:
   - team totals present  -> collect them (the gold data).
   - only match O/U present (likely) -> collect MATCH O/U 2.5 + 1X2 instead.
     Still useful: validates anchoring historically + a match-total baseline;
     the team-total threshold then comes forward from live CLV.

   COLLECTION: source = OddsPortal archives (WC 2022: 64 matches, Euro 2024:
   51). For a finished match the table already shows the CLOSING odds; use the
   "Average" row (or Pinnacle's row). Aim ~30–50 matches; 20 is a useful start
   — don't grind to burnout. One row per market per match.

   TEMPLATE: data/manual/historical_prop_lines.csv (header already in git):
   `tournament,date,home_team,away_team,market,line,over_odds,under_odds,book,is_closing,source_url`
   - market: `match_total` | `team_total:home` | `team_total:away` |
     `corners` | `cards`  (:home/:away = the listed home/away team)
   - line: half-goal (2.5 for match O/U, 1.5 for a team total)
   - over_odds/under_odds: decimal; book: `oddsportal_avg` (or the named book);
     is_closing: TRUE. Team names as shown on the site (eval resolves aliases).
   Example rows:
   `UEFA Euro,2024-07-14,Spain,England,match_total,2.5,2.10,1.75,oddsportal_avg,TRUE,https://...`
   `FIFA World Cup,2022-12-18,Argentina,France,match_total,2.5,1.95,1.90,oddsportal_avg,TRUE,https://...`

   EVAL SCRIPT (AGENT, build once rows land — suggest src/wc26/backtest/
   prop_lines.py + `wc26 eval-prop-lines`): join each row to the realized 90'
   result (results.parquet / match_stats.parquet, team pair ±1 day D013, ET
   rows excluded D017), de-vig each two-way close (D005), and report per market
   family: (1) the closing line's calibration vs outcomes (binary log-loss +
   calibration slope of the de-vigged closing prob) — i.e. how sharp the
   close is; (2) for team totals, compare the model/anchored prob to the
   closing prob (model-vs-line hit rate, the PLAN 3.4 ask); (3) the
   distribution of |closing_fair_p − outcome| → a defensible edge_threshold
   (#8). Pin the verdict in a test like the other experiments.

   Owner: HUMAN (collection, ~2–4 h) or AGENT-with-Chrome if the extension is
   connected; eval script + threshold derivation: AGENT.

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

8. **Re-derive edge_threshold from data** — [edge] — **RESOLVED 2026-06-13 (D036): keep 0.05 as a FLOOR; team-total threshold stays forward-derived from live CLV.**
   - 0.05 was a Phase-0 guess; it is below the measured mean model-market
     disagreement (0.074). The #3 sample confirms this: the live anchor-vs-close
     edge has median |edge| 0.064 (p75 0.087), so 0.05 sits below the median
     disagreement. BUT the disagreement edge is not bankable on this sample
     (hit 58-61% at t<=0.07 on a 0.03 corr gap at n~100, flips negative past
     t=0.10 where the grid is miscalibrated), and these are MATCH not TEAM
     totals on consensus (not Superbet) prices. So the data does not justify
     lowering 0.05, and raising toward p75 would chase grid artifacts. The
     team-total threshold is set FORWARD from live CLV vs the snapshot close
     (D033/D034), already running — not from this sample.

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
