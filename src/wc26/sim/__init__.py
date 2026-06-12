"""Tournament simulator (Phase 5): group state, knockout bracket, Monte Carlo.

Pure functions throughout — all file I/O happens in the CLI layer (and the
explicit loaders in bracket.py / snapshots.py, which the CLI calls). The
simulator exists for country rankings and knockout context (cards stakes
feature), never for pricing bets: futures stay unbettable (PLAN 5.5), and the
extra-time/penalties resolution is for ADVANCEMENT only (D004/D024).
"""
