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
    """Model probabilities for a match day (1X2, totals, props)."""
    _stub("Phase 2 (1X2/totals) and Phase 3 (props)")


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
    """Re-fit models on latest data and version the parameters."""
    _stub("Phase 2")


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
