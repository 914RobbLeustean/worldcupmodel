"""Single Typer entry point. Commands landed phase by phase (docs/PLAN.md);
Phase 5 (sim/rankings) completed the set.
"""

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    import pandas as pd

    from wc26.config import Settings
    from wc26.markets.anchors import MatchAnchor
    from wc26.markets.lines import TwoWayLine
    from wc26.models.goal_engine import GoalEngineParams
    from wc26.sim.bracket import Bracket
    from wc26.sim.tracker import GroupStage, KnockoutFact

    SimInputs = tuple[
        Settings,
        GoalEngineParams,
        GroupStage,
        Bracket,
        dict[frozenset[str], dict[str, str]],
        dict[str, float],
        tuple[KnockoutFact, ...],
    ]

app = typer.Typer(no_args_is_help=True, help="WC26 Edge Model CLI")


def fixture_stage(
    fixtures: "pd.DataFrame",
    home_id: str,
    away_id: str,
    date: "pd.Timestamp",
    knockout_start: "pd.Timestamp",
) -> tuple[int, bool]:
    """(matchday, knockout) for one WC26 fixture, from the calendar alone.

    A fixture on/after the bracket's first knockout date is a knockout match
    (matchday is meaningless there and returned as 0). Group matchday counts
    each team's earlier GROUP fixtures only — knockout rows in the table
    must not inflate it.
    """
    if date >= knockout_start:
        return 0, True
    group_rows = fixtures[fixtures["date"] < knockout_start]
    matchday = int(
        min(
            (group_rows["home_id"].eq(t) | group_rows["away_id"].eq(t))[
                group_rows["date"] < date
            ].sum()
            for t in (home_id, away_id)
        )
        + 1
    )
    return matchday, False


@app.command()
def predict(date: str = typer.Option(None, help="YYYY-MM-DD, default today")) -> None:
    """Model probabilities for a match day: 1X2 + team totals, corners, cards."""
    import numpy as np
    import pandas as pd

    from wc26.data.results import PROCESSED_DIR
    from wc26.models.cards import CardsParams, latest_cards_path, predict_cards
    from wc26.models.corners import CornersParams, latest_corners_path, predict_corners
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path, predict_grid
    from wc26.models.prop_features import is_rivalry, load_rivalries
    from wc26.models.team_totals import distribution_mean_var, goal_marginals, p_over
    from wc26.sim.bracket import load_bracket

    params = GoalEngineParams.load(latest_params_path())
    corners_params = CornersParams.load(latest_corners_path())
    cards_params = CardsParams.load(latest_cards_path())
    rivalries = load_rivalries()
    day = pd.Timestamp(date) if date else pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    todays = fixtures[fixtures["date"].dt.normalize() == day.normalize()]
    if todays.empty:
        typer.echo(f"no WC26 fixtures on {day.date()}")
        raise typer.Exit(code=1)

    # Referee assignments land ~2 days out; optional manual entry file
    # (date,home_id,away_id,referee — ESPN spelling) feeds the cards model.
    ref_path = PROCESSED_DIR.parent / "manual" / "ref_assignments.csv"
    refs: dict[tuple[str, str], str] = {}
    if ref_path.exists():
        ref_df = pd.read_csv(ref_path, parse_dates=["date"])
        refs = {
            (str(r.home_id), str(r.away_id)): str(r.referee)
            for r in ref_df.itertuples(index=False)
            if pd.Timestamp(str(r.date)).normalize() == day.normalize()
        }

    ko_start = pd.Timestamp(min(m.date for m in load_bracket().matches))
    typer.echo(f"models: {params.version} | {corners_params.version} | {cards_params.version}")
    for row in todays.itertuples(index=False):
        home, away = str(row.home_id), str(row.away_id)
        neutral = bool(row.neutral)
        grid = predict_grid(params, home, away, neutral=neutral)
        p_home, p_draw, p_away = grid.home_draw_away
        home_dist, away_dist = goal_marginals(grid)
        matchday, knockout = fixture_stage(
            fixtures, home, away, pd.Timestamp(str(row.date)), ko_start
        )
        corners_dist = predict_corners(
            corners_params, params, home, away, neutral, matchday, knockout=knockout
        )
        cards_pred = predict_cards(
            cards_params,
            home,
            away,
            refs.get((home, away)),
            knockout=knockout,
            rivalry=is_rivalry(home, away, rivalries),
        )

        label = f"{home} v {away}" + ("" if neutral else " (home adv)")
        stage_tag = "[KO — 90' probabilities; can draw]" if knockout else f"[MD{matchday}]"
        typer.echo(f"\n{label}  {stage_tag}")
        typer.echo(
            f"  1X2          {p_home:5.3f} / {p_draw:5.3f} / {p_away:5.3f}   "
            f"lam {grid.home_goal_expectation:.2f}/{grid.away_goal_expectation:.2f}"
        )
        typer.echo(
            f"  team totals  {home}: O1.5 {p_over(home_dist, 1.5):.3f}  "
            f"O2.5 {p_over(home_dist, 2.5):.3f} | {away}: O1.5 {p_over(away_dist, 1.5):.3f}  "
            f"O2.5 {p_over(away_dist, 2.5):.3f}"
        )
        over25 = float(grid.total_goals("over", 2.5))
        typer.echo(
            f"  match O/U    O2.5 {over25:.3f} U2.5 {1 - over25:.3f}   "
            f"[NOT validated for pricing — docs/MODEL.md]"
        )
        c_mean, c_var = distribution_mean_var(corners_dist)
        typer.echo(
            f"  corners      mu {c_mean:4.1f} sd {np.sqrt(c_var):3.1f}   "
            f"O8.5 {p_over(corners_dist, 8.5):.3f}  O9.5 {p_over(corners_dist, 9.5):.3f}  "
            f"O10.5 {p_over(corners_dist, 10.5):.3f}   [reference only — D021]"
        )
        k_mean, k_var = distribution_mean_var(cards_pred.distribution)
        ref_label = (
            f"ref known: {refs.get((home, away))}"
            if cards_pred.ref_known
            else "REF UNKNOWN — mean rate, widened variance"
        )
        typer.echo(
            f"  cards        mu {k_mean:4.1f} sd {np.sqrt(k_var):3.1f}   "
            f"O3.5 {p_over(cards_pred.distribution, 3.5):.3f}  "
            f"O4.5 {p_over(cards_pred.distribution, 4.5):.3f}   "
            f"[{ref_label}] [reference only — D021]"
        )
    typer.echo(
        "\n(90' probabilities; knockouts can draw. Only TEAM TOTALS passed the "
        "Phase 3 gates — match totals D019 and corners/cards D021 are not "
        "validated for pricing.)"
    )


def _load_engine_params() -> "GoalEngineParams":
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path

    return GoalEngineParams.load(latest_params_path())


def _engine_p_over(params: "GoalEngineParams", quote: "TwoWayLine") -> float:
    """Engine-grid P(over) for a team-total quote (reference/context only now —
    D028 retired the engine grid as the pricing source; w*=0.00 vs market)."""
    from wc26.models.goal_engine import predict_grid
    from wc26.models.team_totals import goal_marginals, p_over

    grid = predict_grid(params, quote.home_id, quote.away_id, neutral=quote.neutral)
    home_dist, away_dist = goal_marginals(grid)
    dist = home_dist if quote.team_id == quote.home_id else away_dist
    return p_over(dist, quote.line)


def _anchored_p_over(
    params: "GoalEngineParams", quote: "TwoWayLine", anchor: "MatchAnchor"
) -> tuple[float, str]:
    """Market-anchored P(over) for a team-total quote + the pricing version.

    Prices off the DC grid solved to reproduce the book's de-vigged 1X2
    (D028), with rho from the latest engine fit (versioned, second-order per
    the experiment). Markets code never computes model probabilities; this
    CLI-layer glue calls the solver and hands a float down.
    """
    from wc26.models.market_anchor import market_anchored_grid
    from wc26.models.team_totals import goal_marginals, p_over

    grid = market_anchored_grid(anchor.fair_p_home, anchor.fair_p_away, rho=params.rho)
    home_dist, away_dist = goal_marginals(grid)
    dist = home_dist if quote.team_id == quote.home_id else away_dist
    return p_over(dist, quote.line), f"anchor+{params.version}"


def _anchored_fair_p_over(
    params: "GoalEngineParams",
    fair_p_home: float,
    fair_p_away: float,
    team_is_home: bool,
    line: float,
) -> float:
    """P(team over `line`) from the grid anchored on a de-vigged 1X2 (D033/#15)."""
    from wc26.models.market_anchor import market_anchored_grid
    from wc26.models.team_totals import goal_marginals, p_over

    grid = market_anchored_grid(fair_p_home, fair_p_away, rho=params.rho)
    home_dist, away_dist = goal_marginals(grid)
    return p_over(home_dist if team_is_home else away_dist, line)


@app.command()
def edges() -> None:
    """Compare market-anchored pricing vs data/manual/lines.csv; print +EV bets.

    Pricing is market-anchored (D028): each team total is priced from the DC
    grid solved to reproduce the book's de-vigged 1X2 (data/manual/anchors.csv),
    NOT the engine grid — the engine's 1X2 opinion earned blend weight w*=0.00
    out-of-sample. A quote whose match has no anchor is UNPRICEABLE and cannot
    be flagged a bet (no anchor, no bet). The engine P(over) is shown for
    context only.

    Hard guards (refuse, never skip): quarantined/unknown markets, matches
    without a prediction, stale quotes (>24 h), unknown teams.
    """
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.results import PROCESSED_DIR
    from wc26.markets.anchors import (
        ANCHORS_PATH,
        load_anchors,
        load_snapshot_anchors,
        pick_anchor,
    )
    from wc26.markets.edges import evaluate, rank
    from wc26.markets.lines import LINES_PATH, load_lines

    settings = load_settings()
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    quotes = load_lines(fixtures)
    if not quotes:
        typer.echo(f"no lines in {LINES_PATH} — enter today's book quotes first")
        raise typer.Exit(code=1)
    manual = load_anchors(fixtures)
    snaps = load_snapshot_anchors(fixtures)
    params = _load_engine_params()

    priceable = []  # (Edge, engine_p_over, source_label)
    unpriced = []  # quotes with no anchor at all
    version = f"anchor+{params.version}"
    for quote in quotes:
        anchor, label = pick_anchor(manual, snaps, quote.match, quote.book)
        eng_p = _engine_p_over(params, quote)
        if anchor is None:
            unpriced.append(quote)
            continue
        p_over_anchor, _ = _anchored_p_over(params, quote, anchor)
        priceable.append((evaluate(quote, p_over_anchor), eng_p, label))

    typer.echo(
        f"pricing {version} | edge threshold {settings.edge_threshold:.0%} | "
        f"flat stake {settings.unit_stake:.2f} ({settings.unit_pct:.1%} of {settings.bankroll:.0f})"
    )
    typer.echo(
        f"\n{'':4s}{'match':28s} {'market':18s} {'book':9s} {'src':6s} "
        f"{'odds':>6s} {'fair':>6s} {'anchor':>7s} {'eng':>6s} {'edge':>7s} "
        f"{'ev':>7s} {'stake':>6s}"
    )
    ranked = rank([e for e, _, _ in priceable])
    ctx = {id(e): (eng_p, label) for e, eng_p, label in priceable}
    _src_tag = {"book": "book", "snapshot": "snap"}
    for e in ranked:
        eng_p, label = ctx[id(e)]
        bet = e.edge >= settings.edge_threshold
        stake = f"{settings.unit_stake:.2f}" if bet else "-"
        tag = "BET*" if bet and label != "book" else ("BET " if bet else "    ")
        src = _src_tag.get(label, "xbook")
        typer.echo(
            f"{tag}{e.quote.match:28s} {e.market_label:18s} {e.quote.book:9s} {src:6s} "
            f"{e.odds:6.2f} {e.fair_p:6.3f} {e.model_p:7.3f} "
            f"{(eng_p if e.side == 'over' else 1 - eng_p):6.3f} "
            f"{e.edge:+7.3f} {e.ev:+7.3f} {stake:>6s}"
        )
    for quote in unpriced:
        typer.echo(
            f"  · {quote.match:28s} {quote.team_id + ' ' + str(quote.line):18s} "
            f"{quote.book:9s}        NO ANCHOR — enter the book's 1X2 in "
            f"{ANCHORS_PATH.name} or run `wc26 snapshot-odds` (D028/D033)"
        )
    typer.echo(
        "\n(edge = anchored model_p - de-vigged fair_p; 'anchor' = P(side) from "
        "the 1X2, 'eng' = engine grid (context only, D028). src: book = your "
        "book's anchor, xbook = another book, snap = odds-snapshot fallback; "
        "BET* = non-own-book anchor. Flat stakes — no Kelly.)"
    )


@app.command(name="log-bet")
def log_bet(
    match: str = typer.Option(..., prompt=True, help="'<home> v <away>', any known alias"),
    team: str = typer.Option(..., prompt=True, help="Team the total is on"),
    line: float = typer.Option(..., prompt=True, help="Half-goal line, e.g. 1.5"),
    side: str = typer.Option(..., prompt=True, help="over | under"),
    odds: str = typer.Option(
        "", help="Odds actually taken (decimal or American); default: the lines.csv quote"
    ),
    book: str = typer.Option("", help="Book (required if several books quote this market)"),
    stake: float = typer.Option(0.0, help="Default: flat unit from settings.yaml"),
    note: str = typer.Option("", help="Free-text note"),
) -> None:
    """Append a bet to the append-only ledger (D006).

    The market must be in data/manual/lines.csv (both sides) AND its match must
    have a 1X2 anchor in data/manual/anchors.csv: pricing is market-anchored
    (D028) and a bet without an anchor is refused — no anchor, no bet.
    """
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.results import PROCESSED_DIR
    from wc26.data.teams import registry
    from wc26.markets.anchors import (
        ANCHORS_PATH,
        load_anchors,
        load_snapshot_anchors,
        pick_anchor,
    )
    from wc26.markets.edges import evaluate
    from wc26.markets.ledger import (
        BetRow,
        append_row,
        next_bet_id,
        open_market_conflicts,
        read_ledger,
    )
    from wc26.markets.lines import LineError, load_lines
    from wc26.markets.odds import parse_odds

    settings = load_settings()
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    reg = registry()
    team_id = reg.resolve(team)
    pair = frozenset(reg.resolve(p.strip()) for p in match.split(" v "))
    side = side.strip().lower()
    if side not in ("over", "under"):
        raise LineError(f"side must be over/under, got {side!r}")

    candidates = [
        q
        for q in load_lines(fixtures)
        if frozenset((q.home_id, q.away_id)) == pair
        and q.team_id == team_id
        and q.line == line
        and (not book or q.book == book)
    ]
    if not candidates:
        raise LineError(
            f"no two-way quote for {team_id} O/U {line} in lines.csv — enter both "
            f"sides there first so the logged edge matches `wc26 edges`"
        )
    if len(candidates) > 1:
        raise LineError(
            f"market quoted at several books ({sorted(q.book for q in candidates)}) — pass --book"
        )
    quote = candidates[0]

    anchor, label = pick_anchor(
        load_anchors(fixtures), load_snapshot_anchors(fixtures), quote.match, quote.book
    )
    if anchor is None:
        raise LineError(
            f"no 1X2 anchor for {quote.match} in {ANCHORS_PATH.name} (and no "
            f"odds-snapshot fallback) — pricing is market-anchored (D028) and "
            f"betting is refused without one. Enter the book's home/draw/away "
            f"odds for this match, or run `wc26 snapshot-odds`, then retry."
        )
    params = _load_engine_params()
    p_over_model, version = _anchored_p_over(params, quote, anchor)
    evaluated = evaluate(quote, p_over_model)
    model_p = p_over_model if side == "over" else 1.0 - p_over_model
    fair_p = evaluated.fair_p_over if side == "over" else 1.0 - evaluated.fair_p_over
    odds_taken = (
        parse_odds(odds) if odds else (quote.over_odds if side == "over" else quote.under_odds)
    )
    edge = model_p - fair_p
    if label != "book":
        note = (note + " | " if note else "") + f"anchor source: {label} ({anchor.book})"

    history = read_ledger()
    conflicts = open_market_conflicts(history, quote.match, quote.market)
    if not conflicts.empty:
        held = ", ".join(
            f"{b} ({s} {ln})"
            for b, s, ln in zip(
                conflicts["bet_id"], conflicts["side"], conflicts["line"], strict=True
            )
        )
        raise LineError(
            f"an open bet already rides {quote.market} in this match: {held} — "
            f"correlated lines win/lose together (D029); settle it first or pick "
            f"a different market"
        )
    row = BetRow(
        bet_id=next_bet_id(history),
        ts_utc=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        match=quote.match,
        match_date=str(quote.match_date.date()),
        market=quote.market,
        line=quote.line,
        side=side,
        odds_taken=odds_taken,
        stake=stake if stake > 0 else settings.unit_stake,
        model_prob=model_p,
        model_version=version,
        edge=edge,
        book=quote.book,
        status="open",
        note=note or None,
    )
    append_row(row)
    flag = "" if edge >= settings.edge_threshold else "  [WARNING: below edge threshold]"
    typer.echo(
        f"logged {row.bet_id}: {row.match} {row.market} {side} {line} @ {odds_taken:.3f} "
        f"stake {row.stake:.2f} | model {model_p:.3f} fair {fair_p:.3f} "
        f"edge {edge:+.3f}{flag}"
    )


class SettleDataError(ValueError):
    """The 90' goal count cannot be read from the tables (ET or no result)."""


def goals_90_from_tables(
    stats: "pd.DataFrame",
    results: "pd.DataFrame",
    match_date: "pd.Timestamp",
    home_id: str,
    away_id: str,
    team_id: str,
) -> int:
    """Bet team's 90-minute goals from the results table (D004).

    Refuses (SettleDataError) when the match went to extra time — stored
    scores are 120' totals (D012), so --goals is mandatory then — or when
    the result has not landed yet. Matching is team pair ±1 day (D013).
    """
    import pandas as pd

    near_stats = (stats["date"] - match_date).abs() <= pd.Timedelta(days=1)
    pair_stats = stats["home_id"].isin([home_id, away_id]) & stats["away_id"].isin(
        [home_id, away_id]
    )
    played_stats = stats[near_stats & pair_stats]
    if not played_stats.empty and bool(played_stats.iloc[0]["extra_time"]):
        raise SettleDataError(
            f"{home_id} v {away_id} went to EXTRA TIME — stored scores include ET "
            f"(D012) but the bet settles on 90' (D004). Re-run with "
            f"--goals <{team_id}'s 90-minute goal count>."
        )
    row = results[
        ((results["date"] - match_date).abs() <= pd.Timedelta(days=1))
        & (results["home_id"].isin([home_id, away_id]))
        & (results["away_id"].isin([home_id, away_id]))
    ]
    if row.empty:
        raise SettleDataError(
            f"{home_id} v {away_id} not in the results table yet — run "
            f"`wc26 data scrape --tournament wc2026 && wc26 data sync`, "
            f"or pass --goals"
        )
    result_row = row.iloc[0]
    return int(
        result_row["home_score"]
        if str(result_row["home_id"]) == team_id
        else result_row["away_score"]
    )


def closing_over_source(
    params: "GoalEngineParams",
    home_id: str,
    away_id: str,
    team_id: str,
    line: float,
    closing_over: str,
    closing_under: str,
    anchor_1x2: str,
) -> tuple[float, float, float, str]:
    """Resolve the closing fair P(team over `line`) for settlement (#15).

    Returns (p_over, over_odds_to_store, under_odds_to_store, source_label).
    Priority: an explicit de-vigged prop close -> a manual --anchor-1x2
    H/D/A -> the latest odds snapshot for the match (D033). The anchor paths
    reconstruct vig-free two-way odds so the stored ledger row re-de-vigs to
    the same fair prob. Raises SettleDataError if no source is available.
    """
    from wc26.markets.anchors import devig_1x2, latest_snapshot_1x2
    from wc26.markets.edges import devig_two_way
    from wc26.markets.odds import parse_odds

    if closing_over and closing_under:
        over, under = parse_odds(closing_over), parse_odds(closing_under)
        fair_over, _ = devig_two_way(over, under)
        return fair_over, over, under, "prop-close"

    team_is_home = team_id == home_id
    if anchor_1x2:
        try:
            h, d, a = (parse_odds(x) for x in anchor_1x2.split("/"))
        except ValueError as exc:
            raise SettleDataError(
                f"--anchor-1x2 must be 'HOME/DRAW/AWAY' decimal or American odds, "
                f"got {anchor_1x2!r}"
            ) from exc
        fp_home, _, fp_away = devig_1x2(h, d, a)
        source = "anchor:manual-1x2"
    else:
        snap = latest_snapshot_1x2(home_id, away_id)
        if snap is None:
            raise SettleDataError(
                f"no closing source for {home_id} v {away_id}: pass "
                f"--closing-over/--closing-under (the book's prop close), or "
                f"--anchor-1x2 HOME/DRAW/AWAY, or run `wc26 snapshot-odds` before "
                f"kickoff so a snapshot anchor exists (D033)"
            )
        fp_home, fp_away, ts = snap
        source = f"anchor:snapshot {ts}"

    p_over = _anchored_fair_p_over(params, fp_home, fp_away, team_is_home, line)
    return p_over, round(1.0 / p_over, 4), round(1.0 / (1.0 - p_over), 4), source


@app.command()
def settle(
    bet_id: str = typer.Argument(..., help="e.g. B0001"),
    closing_over: str = typer.Option("", help="Book's closing OVER odds (the prop close)"),
    closing_under: str = typer.Option("", help="Book's closing UNDER odds"),
    anchor_1x2: str = typer.Option(
        "", help="Closing 1X2 as HOME/DRAW/AWAY (e.g. 2.12/3.30/4.09) to anchor CLV"
    ),
    goals: int = typer.Option(
        -1,
        help="Bet team's goals after 90 minutes (D004). Default: read from the "
        "results table — refused if the match went to extra time, because "
        "stored scores include ET (D012); then this flag is mandatory.",
    ),
    note: str = typer.Option(""),
) -> None:
    """Record the result + closing line; compute CLV.

    Closing source priority (#15): the book's two-way prop close
    (--closing-over/--closing-under) -> a manual --anchor-1x2 -> the latest
    odds snapshot for the match (D033, fully automatic if `wc26 snapshot-odds`
    ran before kickoff). The CLV source is stamped in the ledger note.
    Settlement is ALWAYS on the 90-minute score (D004).
    """
    import pandas as pd

    from wc26.data.results import PROCESSED_DIR
    from wc26.markets.ledger import BetRow, append_row, grade_bet, latest_view, read_ledger

    history = read_ledger()
    current = latest_view(history)
    hit = current[current["bet_id"] == bet_id]
    if hit.empty:
        typer.echo(f"no bet {bet_id} in the ledger")
        raise typer.Exit(code=1)
    bet = hit.iloc[0]
    if bet["status"] != "open":
        typer.echo(f"{bet_id} is already {bet['status']} — corrections are new rows")
        raise typer.Exit(code=1)

    home_id, away_id = str(bet["match"]).split(" v ")
    team_id = str(bet["market"]).partition(":")[2]
    side = str(bet["side"])
    line = float(bet["line"])
    if goals < 0:
        stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
        results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
        try:
            goals = goals_90_from_tables(
                stats, results, pd.Timestamp(str(bet["match_date"])), home_id, away_id, team_id
            )
        except SettleDataError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc

    try:
        p_over, over_dec, under_dec, source = closing_over_source(
            _load_engine_params(),
            home_id,
            away_id,
            team_id,
            line,
            closing_over,
            closing_under,
            anchor_1x2,
        )
    except SettleDataError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    fair_p = p_over if side == "over" else 1.0 - p_over
    settlement = grade_bet(
        side=side,
        line=line,
        goals_90=goals,
        odds_taken=float(bet["odds_taken"]),
        stake=float(bet["stake"]),
        fair_closing_p=fair_p,
    )
    src_note = f"clv_src={source}"
    append_row(
        BetRow(
            bet_id=bet_id,
            ts_utc=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            match=str(bet["match"]),
            match_date=str(bet["match_date"]),
            market=str(bet["market"]),
            line=line,
            side=side,
            odds_taken=float(bet["odds_taken"]),
            stake=float(bet["stake"]),
            model_prob=float(bet["model_prob"]),
            model_version=str(bet["model_version"]),
            edge=float(bet["edge"]),
            book=str(bet["book"]),
            status="settled",
            closing_over_odds=over_dec,
            closing_under_odds=under_dec,
            clv=settlement.clv,
            goals_90=goals,
            result=settlement.result,
            pnl=settlement.pnl,
            note=f"{note} | {src_note}" if note else src_note,
        )
    )
    typer.echo(
        f"{bet_id} {settlement.result.upper()}: {team_id} scored {goals} in 90' vs "
        f"{side} {line} | pnl {settlement.pnl:+.2f} | closing fair p "
        f"{settlement.fair_closing_p:.3f} ({source}) -> CLV {settlement.clv:+.3%}"
    )


@app.command(name="clv-report")
def clv_report() -> None:
    """Cumulative CLV, ROI, and calibration of logged bets, by market."""
    from wc26.markets.ledger import clv_report as build_report
    from wc26.markets.ledger import latest_view, read_ledger

    history = read_ledger()
    if history.empty:
        typer.echo("ledger is empty — no bets logged yet")
        raise typer.Exit(code=0)
    current = latest_view(history)
    n_open = int((current["status"] == "open").sum())
    report = build_report(history)
    if report.empty:
        typer.echo(f"{n_open} open bet(s), none settled yet — nothing to report")
        raise typer.Exit(code=0)

    typer.echo(f"settled bets by market ({n_open} still open):\n")
    typer.echo(
        f"{'market':14s} {'bets':>4s} {'staked':>8s} {'pnl':>8s} {'roi':>8s} "
        f"{'CLV':>8s} {'CLVxStk':>8s} {'model_p':>8s} {'win%':>6s}"
    )
    for r in report.itertuples(index=False):
        typer.echo(
            f"{r.market:14s} {r.bets:4d} {r.staked:8.2f} {r.pnl:+8.2f} {r.roi:+8.1%} "
            f"{r.mean_clv:+8.2%} {r.stake_wtd_clv:+8.2%} {r.mean_model_p:8.3f} "
            f"{r.win_rate:6.1%}"
        )
    typer.echo(
        "\n(CLV = odds_taken x de-vigged closing prob - 1; positive = beat the "
        "close. Kelly stays off until CLV > 0 over 50+ bets. 'TOTAL (real)' is "
        "real money only; paper bets are on their own excluded line.)"
    )


@app.command(name="odds-check")
def odds_check() -> None:
    """Budgeted live h2h sanity check vs The Odds API (1 credit, D007 cap).

    Compares model 1X2 to de-vigged market averages for upcoming WC26
    fixtures — a drift alarm, never a pricing path (prop lines stay manual).
    """
    import os

    import numpy as np
    import pandas as pd

    from wc26.backtest.baselines import devig_1x2
    from wc26.config import load_settings
    from wc26.data.odds_api import fetch_h2h
    from wc26.data.results import PROCESSED_DIR
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path, predict_grid

    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        typer.echo("ODDS_API_KEY is not set — get a free key at the-odds-api.com (D007)")
        raise typer.Exit(code=1)
    settings = load_settings()
    quotes = fetch_h2h(api_key, settings.odds_api_budget)
    if not quotes:
        typer.echo("no upcoming WC26 h2h markets returned")
        raise typer.Exit(code=1)

    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    params = GoalEngineParams.load(latest_params_path())
    typer.echo(f"model {params.version} vs {len(quotes)} market h2h averages\n")
    worst = 0.0
    for q in quotes:
        fix = fixtures[
            (fixtures["home_id"] == q.home_id)
            & (fixtures["away_id"] == q.away_id)
            & (~fixtures["played"])
        ]
        if fix.empty:
            typer.echo(f"  {q.home_id} v {q.away_id}: no unplayed fixture — skipped")
            continue
        grid = predict_grid(params, q.home_id, q.away_id, neutral=bool(fix.iloc[0]["neutral"]))
        model = np.array(grid.home_draw_away, dtype=np.float64)
        market = devig_1x2(np.array([[q.home_odds, q.draw_odds, q.away_odds]]))[0]
        diff = float(np.max(np.abs(model - market)))
        worst = max(worst, diff)
        flag = "  <-- CHECK" if diff > settings.backtest.sanity_max_abs_diff else ""
        typer.echo(
            f"  {q.home_id:18s} v {q.away_id:18s} model "
            f"{model[0]:.2f}/{model[1]:.2f}/{model[2]:.2f} market "
            f"{market[0]:.2f}/{market[1]:.2f}/{market[2]:.2f} "
            f"max diff {diff:.3f} ({q.n_books} books){flag}"
        )
    typer.echo(
        f"\nworst per-outcome diff {worst:.3f} "
        f"(sanity ceiling {settings.backtest.sanity_max_abs_diff}, D016)"
    )


@app.command(name="snapshot-odds")
def snapshot_odds() -> None:
    """Capture a point-in-time 1X2 + match-total snapshot (D033, 2 credits).

    Appends market-averaged odds to data/odds_snapshots.csv (in git,
    append-only) and caches the raw response. Run it near each kickoff: the
    latest pre-kickoff snapshot per match is the fallback CLOSING anchor (so a
    missed manual capture no longer loses CLV) and the auto-anchor for
    `wc26 edges`/`log-bet` when no anchors.csv row exists (D028/D032).
    """
    import os

    from wc26.config import load_settings
    from wc26.data.odds_api import (
        SNAPSHOTS_PATH,
        append_snapshots,
        fetch_odds_snapshot,
    )

    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        typer.echo("ODDS_API_KEY is not set — get a free key at the-odds-api.com (D007)")
        raise typer.Exit(code=1)
    settings = load_settings()
    snapshots, snapshot_ts = fetch_odds_snapshot(api_key, settings.odds_api_budget)
    if not snapshots:
        typer.echo("no upcoming WC26 markets returned — nothing captured")
        raise typer.Exit(code=1)
    append_snapshots(snapshots, snapshot_ts)
    with_totals = sum(1 for s in snapshots if s.total_line is not None)
    typer.echo(
        f"captured {len(snapshots)} match snapshots @ {snapshot_ts} "
        f"({with_totals} with totals) -> {SNAPSHOTS_PATH.name}"
    )
    for s in snapshots:
        tot = (
            f" | O/U {s.total_line} {s.over_odds:.2f}/{s.under_odds:.2f}"
            if s.total_line is not None and s.over_odds is not None and s.under_odds is not None
            else ""
        )
        typer.echo(
            f"  {s.home_id:18s} v {s.away_id:18s} "
            f"1X2 {s.home_odds:.2f}/{s.draw_odds:.2f}/{s.away_odds:.2f} "
            f"({s.n_books_h2h} books){tot}"
        )


@app.command(name="add-result")
def add_result(
    date: str = typer.Option(..., prompt=True, help="Match date YYYY-MM-DD"),
    home: str = typer.Option(..., prompt=True, help="Home team (any known alias)"),
    away: str = typer.Option(..., prompt=True, help="Away team (any known alias)"),
    home_score: int = typer.Option(
        ..., prompt=True, min=0, help="STORED score: the 120' total if extra time (D012)"
    ),
    away_score: int = typer.Option(..., prompt=True, min=0),
    extra_time: bool = typer.Option(False, prompt="Extra time? (knockouts only)"),
    shootout_winner: str = typer.Option(
        "",
        prompt="Shootout winner (blank unless pens)",
        help="REQUIRED when extra time ended level — the advancing team (D027)",
    ),
    corners_home: int = typer.Option(-1, prompt="Home corners (-1 if unknown)"),
    corners_away: int = typer.Option(-1, prompt="Away corners (-1 if unknown)"),
    yellows_home: int = typer.Option(-1, prompt="Home yellow cards (-1 if unknown)"),
    yellows_away: int = typer.Option(-1, prompt="Away yellow cards (-1 if unknown)"),
    reds_home: int = typer.Option(-1, prompt="Home red cards (-1 if unknown)"),
    reds_away: int = typer.Option(-1, prompt="Away red cards (-1 if unknown)"),
    fouls_home: int = typer.Option(-1, prompt="Home fouls (-1 if unknown)"),
    fouls_away: int = typer.Option(-1, prompt="Away fouls (-1 if unknown)"),
    shots_home: int = typer.Option(-1, prompt="Home shots (-1 if unknown)"),
    shots_away: int = typer.Option(-1, prompt="Away shots (-1 if unknown)"),
    referee: str = typer.Option("", prompt="Referee (blank if unknown)"),
    tournament: str = typer.Option("FIFA World Cup", prompt=True),
    neutral: bool = typer.Option(True, prompt="Neutral venue?"),
) -> None:
    """Append a finished match (score, stats, referee) and re-ingest.

    Score goes to data/manual/results_patch.csv (overrides the lagging
    upstream CSV); the self-contained stats row (incl. extra_time and the
    shootout winner for knockouts, D027) goes to data/manual/stats_patch.csv.
    Both files are in git — review the diff before committing.
    """
    from wc26.data.manual import append_result

    paths = append_result(
        date=date,
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
        corners_home=corners_home,
        corners_away=corners_away,
        yellows_home=yellows_home,
        yellows_away=yellows_away,
        reds_home=reds_home,
        reds_away=reds_away,
        fouls_home=fouls_home,
        fouls_away=fouls_away,
        shots_home=shots_home,
        shots_away=shots_away,
        referee=referee,
        tournament=tournament,
        neutral=neutral,
        extra_time=extra_time,
        shootout_winner=shootout_winner,
    )
    for path in paths:
        typer.echo(f"appended to {path}")
    from wc26.data.espn import refresh_match_stats_from_patch
    from wc26.data.results import ingest

    ingest()
    if refresh_match_stats_from_patch() is not None:
        typer.echo("re-ingested processed tables (incl. match_stats from the patch)")
    else:
        typer.echo("re-ingested processed tables")


@app.command()
def refit() -> None:
    """Re-fit goal engine + prop models on all current data; version all params."""
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.elo import compute_elo_history, ratings_asof
    from wc26.data.results import PROCESSED_DIR
    from wc26.models.cards import fit_cards
    from wc26.models.corners import fit_corners
    from wc26.models.goal_engine import MODELS_DIR, fit_goal_engine, prepare_training_data
    from wc26.models.prop_features import load_rivalries, props_universe

    settings = load_settings()
    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    # Cutoff = tomorrow: include everything played through today.
    cutoff = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() + pd.Timedelta(days=1)
    train = prepare_training_data(
        results, stats, cutoff, settings.goal_engine.training_window_years
    )
    elo = ratings_asof(compute_elo_history(results, settings.elo_k), cutoff)
    params = fit_goal_engine(train, elo, cutoff, settings)
    path = MODELS_DIR / f"goal_engine_{params.data_cutoff}_{params.git_sha[:7]}.json"
    params.save(path)
    typer.echo(f"fitted on {params.n_matches} matches (window to {params.data_cutoff})")
    typer.echo(f"home_advantage={params.home_advantage:.3f} rho={params.rho:.4f}")
    typer.echo(f"saved {path}")

    # Prop models version alongside the engine: same cutoff + git SHA scheme.
    universe = props_universe(stats, results)
    train_universe = universe[universe["date"] < cutoff]
    corners = fit_corners(train_universe, params, cutoff, settings)
    corners_path = MODELS_DIR / f"corners_{corners.data_cutoff}_{corners.git_sha[:7]}.json"
    corners.save(corners_path)
    typer.echo(
        f"corners: {corners.n_matches} matches, alpha={corners.alpha:.4f}, "
        f"features={corners.feature_names} -> {corners_path.name}"
    )
    cards = fit_cards(train_universe, load_rivalries(), cutoff, settings)
    cards_path = MODELS_DIR / f"cards_{cards.data_cutoff}_{cards.git_sha[:7]}.json"
    cards.save(cards_path)
    typer.echo(
        f"cards: {cards.n_matches} matches, alpha={cards.alpha:.4f}, "
        f"refs={len(cards.ref_rates)}, features={cards.feature_names} -> {cards_path.name}"
    )


@app.command()
def backtest() -> None:
    """Walk-forward backtest vs Elo-only and market baselines; write artifacts."""
    import pandas as pd

    from wc26.backtest.harness import run_backtest, write_artifacts
    from wc26.config import load_settings
    from wc26.data.results import PROCESSED_DIR

    settings = load_settings()
    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    odds_path = PROCESSED_DIR / "market_odds.parquet"
    if not odds_path.exists():
        from wc26.data.market_odds import build_market_odds

        build_market_odds()
    odds = pd.read_parquet(odds_path)
    eval_df, summary = run_backtest(settings, results, stats, odds)
    for path in write_artifacts(eval_df, summary):
        typer.echo(f"wrote {path}")
    typer.echo(f"n={summary['n_matches']} matches, cutoffs={len(summary['cutoffs'])}")
    for model, m in summary["metrics"].items():
        typer.echo(f"{model:8s} log-loss {m['log_loss']:.4f}  brier {m['brier']:.4f}")

    from wc26.backtest.props import run_props_backtest, write_props_artifacts

    totals_df, corners_df, cards_df, props_summary = run_props_backtest(settings, results, stats)
    for path_str in write_props_artifacts(totals_df, corners_df, cards_df, props_summary):
        typer.echo(f"wrote {path_str}")
    for market in ("totals", "corners", "cards"):
        block = props_summary[market]
        if market == "totals":
            line = (
                f"team count-LL {block['count_log_loss']['engine_team']:.4f} "
                f"(naive {block['count_log_loss']['naive_team']:.4f}), "
                f"team O1.5 slope {block['team_o15']['calibration_slope']:.2f}"
            )
        else:
            key = next(k for k in block if k.startswith("o"))
            line = (
                f"count-LL {block['count_log_loss']['model']:.4f} "
                f"(naive {block['count_log_loss']['naive']:.4f}), "
                f"{key.upper()} slope {block[key]['calibration_slope']:.2f}"
            )
        typer.echo(f"{market:8s} n={block['n']}  {line}")

    from wc26.backtest.market_anchor import (
        run_market_anchor_backtest,
        write_market_anchor_artifacts,
    )

    anchor_df, anchor_summary = run_market_anchor_backtest(totals_df, eval_df, odds)
    for path_str in write_market_anchor_artifacts(anchor_df, anchor_summary):
        typer.echo(f"wrote {path_str}")
    ll = anchor_summary["team_count_log_loss"]
    o15 = anchor_summary["team_o15"]
    blend = anchor_summary["blend_1x2"]
    typer.echo(
        f"anchor   n={anchor_summary['n']}  team count-LL {ll['anchored']:.4f} "
        f"(engine {ll['engine']:.4f}, naive {ll['naive']:.4f}), "
        f"team O1.5 slope {o15['anchored_calibration_slope']:.2f} "
        f"(engine {o15['engine_calibration_slope']:.2f}); "
        f"1X2 blend w*={blend['w_star']:.2f} LL {blend['log_loss_at_w_star']:.4f}"
    )

    from wc26.backtest.wc_offset import run_wc_offset_experiment, write_wc_offset_artifact

    wc_summary = run_wc_offset_experiment(settings, results, stats)
    typer.echo(f"wrote {write_wc_offset_artifact(wc_summary)}")
    wb, wo = wc_summary["base"], wc_summary["offset"]
    typer.echo(
        f"wc_offset n={wc_summary['n_wc_matches']}  WC 1X2-LL {wb['x1x2_log_loss']:.4f}"
        f"->{wo['x1x2_log_loss']:.4f}  team-LL {wb['team_count_log_loss']:.4f}"
        f"->{wo['team_count_log_loss']:.4f}  total {wb['pred_total_mean']:.2f}"
        f"->{wo['pred_total_mean']:.2f} (real {wb['realized_total_mean']:.2f}); "
        f"engine default OFF (D035)"
    )


@app.command()
def eval_prop_lines() -> None:
    """Score the historical consensus match-total closes (backlog #3/#8, D036)."""
    import pandas as pd

    from wc26.backtest.prop_lines import run_prop_lines_eval, write_prop_lines_artifacts
    from wc26.data.historical_prop_lines import load_historical_prop_lines
    from wc26.data.results import PROCESSED_DIR

    prop = load_historical_prop_lines()
    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    odds = pd.read_parquet(PROCESSED_DIR / "market_odds.parquet")
    df, summary = run_prop_lines_eval(prop, results, stats, odds)
    for path_str in write_prop_lines_artifacts(df, summary):
        typer.echo(f"wrote {path_str}")

    cal = summary["close_calibration"]["2.5"]
    anc = summary["anchoring"]
    slope = cal["calibration_slope"]
    slope_str = f"{slope:.2f}" if slope is not None else "n/a"
    typer.echo(
        f"prop-lines n={summary['n_matches']} matches ({summary['n_lines']} lines)  "
        f"consensus close (D036)"
    )
    typer.echo(
        f"  O2.5 close: log-loss {cal['close_log_loss']:.4f} vs naive "
        f"{cal['naive_log_loss']:.4f} (skill {cal['log_loss_skill_vs_naive']:+.4f}), "
        f"discrimination corr {cal['corr_with_outcome']:.3f}, slope {slope_str}"
    )
    typer.echo(
        f"  anchoring (D028): anchored vs close P(O2.5) corr {anc['corr_p_over']:.3f}, "
        f"mean|Δ| {anc['mean_abs_diff_p_over']:.4f}; "
        f"anchored LL {anc['anchored_log_loss']:.4f} ~ close LL {anc['close_log_loss']:.4f}"
    )
    et = summary["edge_threshold"]
    q = et["abs_edge_quantiles"]
    typer.echo(
        f"  #8 anchor-vs-close edge: median|edge| {q['0.5']:.3f}, p75 {q['0.75']:.3f}; "
        f"current threshold 0.05 sits below the median disagreement"
    )


def _sim_inputs() -> "SimInputs":
    """Load everything the simulator needs (the CLI owns all I/O)."""
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.elo import compute_elo_history, ratings_asof
    from wc26.data.results import PROCESSED_DIR
    from wc26.data.teams import registry
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path
    from wc26.sim.bracket import load_allocation, load_bracket
    from wc26.sim.tracker import build_group_stage, knockout_facts

    settings = load_settings()
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    stats = pd.read_parquet(PROCESSED_DIR / "match_stats.parquet")
    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    params = GoalEngineParams.load(latest_params_path())
    bracket = load_bracket()
    ko_start = pd.Timestamp(min(m.date for m in bracket.matches))
    reg = registry()
    stage = build_group_stage(fixtures, stats, reg, knockout_start=ko_start)
    facts = knockout_facts(fixtures, stats, reg, knockout_start=ko_start)
    allocation = load_allocation(bracket)
    asof = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() + pd.Timedelta(days=1)
    elo_series = ratings_asof(compute_elo_history(results, settings.elo_k), asof)
    elo = {str(k): float(v) for k, v in elo_series.items()}
    return settings, params, stage, bracket, allocation, elo, facts


@app.command()
def sim() -> None:
    """Monte Carlo of the remaining tournament: group state + advancement.

    Group standings use the official 2026 tiebreakers; statuses mark teams
    whose advancement is mathematically decided; MD3 dead rubbers
    (historically the softest lines) are flagged. Advancement probabilities
    come from the seeded MC — for rankings and knockout context, NEVER for
    betting futures (PLAN 5.5).
    """
    from wc26.sim.mc import run_simulation
    from wc26.sim.tracker import tournament_state

    settings, params, stage, bracket, allocation, elo, facts = _sim_inputs()
    state = tournament_state(stage, elo, settings.seed)
    out = run_simulation(
        params, stage, bracket, allocation, elo, settings.seed, settings.mc_runs, ko_facts=facts
    )
    n = float(out.n_runs)
    typer.echo(f"model {out.model_version} | {out.n_runs} runs, seed {out.seed}\n")
    for letter in sorted(stage.groups):
        ga = state.analyses[letter]
        typer.echo(f"Group {letter}")
        for team in ga.order_now:
            st = ga.statuses[team]
            i = out.teams.index(team)
            flag = "  [THROUGH]" if st.secured_advance else ("  [OUT]" if st.eliminated else "")
            typer.echo(
                f"  {st.rank_now}. {team:22s} MP{st.played} {st.points}pts "
                f"gd{st.gd:+d} gf{st.gf:<2d} | win grp {out.group_win[i] / n:5.1%} "
                f"top2 {out.top2[i] / n:5.1%} 3rd-q {out.third_qualified[i] / n:5.1%} "
                f"adv {out.reached[i, 1] / n:5.1%}{flag}"
            )
    if state.dead_rubbers:
        typer.echo("\nMD3 dead rubbers (qualification decided for BOTH teams):")
        for d in state.dead_rubbers:
            typer.echo(f"  group {d.group}: {d.home_id} v {d.away_id}")
    typer.echo(
        "\n(advancement only — the ET/pens layer never prices bets, D004/D023; "
        "futures are not bettable, PLAN 5.5)"
    )


@app.command()
def rankings(diff: bool = typer.Option(False, help="Show movement vs previous snapshot")) -> None:
    """Per-team P(R32..champion) + expected finish for all 48; dated snapshot."""
    import datetime as dt

    import pandas as pd

    from wc26.sim.mc import rankings_frame, run_simulation
    from wc26.sim.snapshots import diff_frames, previous_snapshot, save_snapshot

    settings, params, stage, bracket, allocation, elo, facts = _sim_inputs()
    out = run_simulation(
        params, stage, bracket, allocation, elo, settings.seed, settings.mc_runs, ko_facts=facts
    )
    frame = rankings_frame(out)
    today = dt.datetime.now(tz=dt.UTC).date()
    path = save_snapshot(frame, today, out.model_version, out.n_runs, out.seed)

    typer.echo(f"model {out.model_version} | {out.n_runs} runs, seed {out.seed}")
    typer.echo(
        f"\n{'rk':>3s} {'team':22s} {'grp':3s} {'R32':>6s} {'R16':>6s} {'QF':>6s} "
        f"{'SF':>6s} {'final':>6s} {'champ':>6s} {'E[stage]':>8s}"
    )
    for r in frame.itertuples(index=False):
        typer.echo(
            f"{r.rank:3d} {r.team_id:22s} {r.group:3s} {r.p_r32:6.1%} {r.p_r16:6.1%} "
            f"{r.p_qf:6.1%} {r.p_sf:6.1%} {r.p_final:6.1%} {r.p_champion:6.1%} "
            f"{r.exp_stage:8.2f}"
        )
    typer.echo(f"\nsnapshot {path}")

    if diff:
        prev_path = previous_snapshot(today)
        if prev_path is None:
            typer.echo("no earlier snapshot to diff against")
            raise typer.Exit(code=0)
        moves = diff_frames(frame, pd.read_parquet(prev_path))
        typer.echo(f"\nmovement vs {prev_path.name}:")
        typer.echo(f"{'rk':>3s} {'mv':>3s} {'team':22s} {'dR32':>7s} {'dQF':>7s} {'dchamp':>7s}")
        for r in moves.itertuples(index=False):
            typer.echo(
                f"{r.rank:3d} {r.rank_move:+3d} {r.team_id:22s} {r.d_p_r32:+7.3f} "
                f"{r.d_p_qf:+7.3f} {r.d_p_champion:+7.3f}"
            )


data_app = typer.Typer(no_args_is_help=True, help="Ingest and inspect data tables.")
app.add_typer(data_app, name="data")


@data_app.command(name="elo")
def data_elo(top: int = typer.Option(15, help="How many teams to show")) -> None:
    """Current Elo ratings (computed in-repo, full history)."""
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.elo import compute_elo_history, ratings_asof
    from wc26.data.results import PROCESSED_DIR

    results = pd.read_parquet(PROCESSED_DIR / "results.parquet")
    history = compute_elo_history(results, load_settings().elo_k)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None) + pd.Timedelta(days=1)
    for rank, (team, rating) in enumerate(ratings_asof(history, today).nlargest(top).items(), 1):
        typer.echo(f"{rank:3d}. {team:25s} {rating:7.1f}")


@data_app.command(name="ingest")
def data_ingest() -> None:
    """Build processed tables (results, fixtures) from raw + manual patch."""
    from wc26.data.results import ingest

    for name, path in ingest().items():
        typer.echo(f"wrote {name}: {path}")


@data_app.command(name="scrape")
def data_scrape(
    tournament: str = typer.Option(
        "", help="One of wc2018, wc2022, euro2024, copa2024, wc2026; empty = all"
    ),
) -> None:
    """Fetch match stats (corners, cards, referee) from ESPN into parquet.

    Fully cached: finished matches are never re-fetched, so re-runs are cheap
    and the command is safe to interrupt and resume.
    """
    from wc26.data.espn import TOURNAMENTS, build_match_stats, build_referees

    keys = [tournament] if tournament else list(TOURNAMENTS)
    for key in keys:
        if key not in TOURNAMENTS:
            typer.echo(f"unknown tournament {key!r}; choose from {list(TOURNAMENTS)}")
            raise typer.Exit(code=2)
    stats = build_match_stats(keys if tournament else None)
    refs = build_referees(stats)
    typer.echo(f"match_stats: {len(stats)} matches; referees: {len(refs)}")


@data_app.command(name="sync")
def data_sync() -> None:
    """Write finished WC26 results from ESPN stats into the results patch,
    then rebuild the processed tables."""
    from wc26.data.results import ingest
    from wc26.data.sync import sync_wc26_results

    report = sync_wc26_results()
    for line in report.appended:
        typer.echo(f"new result: {line}")
    if report.swapped_home_away:
        typer.echo(f"note: home/away swapped vs ESPN for {report.swapped_home_away}")
    typer.echo(f"appended {len(report.appended)}, already known {report.skipped_already_known}")
    if report.appended:
        ingest()
        typer.echo("re-ingested processed tables")


@data_app.command(name="status")
def data_status() -> None:
    """Row counts and freshness for every ingested table."""
    from wc26.data.results import freshness

    for name, line in freshness().items():
        typer.echo(f"{name:10s} {line}")


if __name__ == "__main__":
    app()
