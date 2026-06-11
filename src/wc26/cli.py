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
def add_result() -> None:
    """Append a finished match (score, corners, cards, referee)."""
    _stub("Phase 1")


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


@app.command(name="data")
def data_status() -> None:
    """Row counts and freshness for every ingested table."""
    _stub("Phase 1")


if __name__ == "__main__":
    app()
