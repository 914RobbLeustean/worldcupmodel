"""Phase 0 smoke tests: package imports, CLI wires up, settings load and
encode the money-rule guard rails."""

from typer.testing import CliRunner

import wc26
from wc26.cli import app
from wc26.config import load_settings

runner = CliRunner()


def test_package_imports() -> None:
    assert wc26.__version__


def test_cli_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in [
        "predict",
        "edges",
        "log-bet",
        "settle",
        "clv-report",
        "add-result",
        "refit",
        "sim",
        "rankings",
    ]:
        assert cmd in result.output


def test_no_stub_commands_remain() -> None:
    # Phase 5 delivered sim/rankings, completing the CLI surface: every
    # command responds to --help (stubs used to exit 1 with a phase pointer).
    for cmd in ("sim", "rankings"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0


def test_settings_load_and_guard_rails() -> None:
    s = load_settings()
    assert s.kelly_enabled is False
    assert 0 < s.unit_pct <= 0.02, "flat stakes must stay small"
    assert s.edge_threshold >= 0.05, "edge floor must not be lowered casually"
    assert s.unit_stake == s.bankroll * s.unit_pct
    assert s.elo_k["world_cup"] > s.elo_k["friendly"]
