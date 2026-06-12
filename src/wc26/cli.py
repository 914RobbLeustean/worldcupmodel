"""Single Typer entry point. Commands land phase by phase (docs/PLAN.md);
unbuilt commands say which phase delivers them and exit non-zero.
"""

import typer

app = typer.Typer(no_args_is_help=True, help="WC26 Edge Model CLI")


def _stub(phase: str) -> None:
    typer.echo(f"Not implemented yet — arrives in {phase}. See STATUS.md / docs/PLAN.md.")
    raise typer.Exit(code=1)


@app.command()
def predict(date: str = typer.Option(None, help="YYYY-MM-DD, default today")) -> None:
    """Model probabilities for a match day (1X2, totals; props in Phase 3)."""
    import pandas as pd

    from wc26.data.results import PROCESSED_DIR
    from wc26.models.goal_engine import GoalEngineParams, latest_params_path, predict_grid

    params = GoalEngineParams.load(latest_params_path())
    day = pd.Timestamp(date) if date else pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    fixtures = pd.read_parquet(PROCESSED_DIR / "fixtures.parquet")
    todays = fixtures[fixtures["date"].dt.normalize() == day.normalize()]
    if todays.empty:
        typer.echo(f"no WC26 fixtures on {day.date()}")
        raise typer.Exit(code=1)

    typer.echo(f"model: {params.version} (fitted {params.fitted_at})")
    typer.echo(
        f"{'match':40s} {'1':>6s} {'X':>6s} {'2':>6s}  {'O2.5':>6s} {'U2.5':>6s}  lam_h/lam_a"
    )
    for row in todays.itertuples(index=False):
        home, away = str(row.home_id), str(row.away_id)
        grid = predict_grid(params, home, away, neutral=bool(row.neutral))
        p_home, p_draw, p_away = grid.home_draw_away
        over = float(grid.total_goals("over", 2.5))
        label = f"{home} v {away}" + ("" if bool(row.neutral) else " (home adv)")
        typer.echo(
            f"{label:40s} {p_home:6.3f} {p_draw:6.3f} {p_away:6.3f}  "
            f"{over:6.3f} {1 - over:6.3f}  {grid.home_goal_expectation:.2f}/"
            f"{grid.away_goal_expectation:.2f}"
        )
    typer.echo("(90-minute probabilities; knockout matches can draw)")


@app.command()
def edges() -> None:
    """Compare model vs data/manual/lines.csv and print +EV bets."""
    _stub("Phase 4")


@app.command(name="log-bet")
def log_bet() -> None:
    """Append a bet to the append-only ledger."""
    _stub("Phase 4")


@app.command()
def settle() -> None:
    """Record results + closing lines for open bets; compute CLV."""
    _stub("Phase 4")


@app.command(name="clv-report")
def clv_report() -> None:
    """Cumulative CLV, ROI, and calibration of logged bets."""
    _stub("Phase 4")


@app.command(name="add-result")
def add_result(
    date: str = typer.Option(..., prompt=True, help="Match date YYYY-MM-DD"),
    home: str = typer.Option(..., prompt=True, help="Home team (any known alias)"),
    away: str = typer.Option(..., prompt=True, help="Away team (any known alias)"),
    home_score: int = typer.Option(..., prompt=True, min=0),
    away_score: int = typer.Option(..., prompt=True, min=0),
    corners_home: int = typer.Option(-1, prompt="Home corners (-1 if unknown)"),
    corners_away: int = typer.Option(-1, prompt="Away corners (-1 if unknown)"),
    yellows_home: int = typer.Option(-1, prompt="Home yellow cards (-1 if unknown)"),
    yellows_away: int = typer.Option(-1, prompt="Away yellow cards (-1 if unknown)"),
    reds_home: int = typer.Option(-1, prompt="Home red cards (-1 if unknown)"),
    reds_away: int = typer.Option(-1, prompt="Away red cards (-1 if unknown)"),
    referee: str = typer.Option("", prompt="Referee (blank if unknown)"),
    tournament: str = typer.Option("FIFA World Cup", prompt=True),
    neutral: bool = typer.Option(True, prompt="Neutral venue?"),
) -> None:
    """Append a finished match (score, corners, cards, referee) and re-ingest.

    Score goes to data/manual/results_patch.csv (overrides the lagging Kaggle
    CSV); corners/cards/ref go to data/manual/stats_patch.csv for the prop
    models. Both files are in git — review the diff before committing.
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
        referee=referee,
        tournament=tournament,
        neutral=neutral,
    )
    for path in paths:
        typer.echo(f"appended to {path}")
    from wc26.data.results import ingest

    ingest()
    typer.echo("re-ingested processed tables")


@app.command()
def refit() -> None:
    """Re-fit the goal engine on all current data and version the params."""
    import pandas as pd

    from wc26.config import load_settings
    from wc26.data.elo import compute_elo_history, ratings_asof
    from wc26.data.results import PROCESSED_DIR
    from wc26.models.goal_engine import MODELS_DIR, fit_goal_engine, prepare_training_data

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


@app.command()
def sim() -> None:
    """Monte Carlo simulation of the remaining tournament."""
    _stub("Phase 5")


@app.command()
def rankings(diff: bool = typer.Option(False, help="Show movement vs previous snapshot")) -> None:
    """Per-team advancement/champion probabilities for all 48 teams."""
    _stub("Phase 5")


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
