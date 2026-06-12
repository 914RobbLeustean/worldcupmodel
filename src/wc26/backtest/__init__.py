"""Walk-forward backtesting. The ONLY evaluation path for models (CLAUDE.md):
every prediction is made from a fit whose data ends strictly before the
match date. Generic over models — Phase 3 prop models reuse the harness.
"""
