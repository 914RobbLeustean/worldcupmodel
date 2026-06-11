# Daily tournament playbook

> The exact match-day routine, for the user or an agent. Finalized in Phase 4;
> draft below reflects the target flow.

1. `wc26 add-result` — enter yesterday's finals (score, corners, cards, ref).
2. `wc26 refit` — per refit policy (see DECISIONS.md once decided).
3. `wc26 predict --date <today>` — model probabilities for today's matches.
4. `wc26 rankings --diff` — updated tournament rankings, movement vs yesterday.
5. Enter today's prop lines from the book into data/manual/lines.csv.
6. `wc26 edges` — review +EV table; bet only edges ≥ threshold (settings.yaml).
7. `wc26 log-bet` — record every bet immediately, with odds actually taken.
8. At kickoff: record closing lines; `wc26 settle` yesterday's bets.
9. Weekly: `wc26 clv-report` — if CLV ≤ 0 after 50 bets, stop betting, review.

Money rules (non-negotiable): flat 1.5% units, 5% edge floor, no Kelly until
CLV > 0 over 50+ bets, no futures bets without a healthy simulator and CLV.
