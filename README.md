# WC26 Edge Model

World Cup 2026 prediction pipeline that prices match props (corners, cards,
team totals), flags +EV bets against manually entered sportsbook lines, ranks
all 48 teams via Monte Carlo simulation, and tracks closing line value (CLV).

## Quickstart

```bash
uv sync          # install everything (Python 3.12 pinned)
make test        # must be green
uv run wc26 --help
```

## How this project is run

This repo is operated by AI agents across sessions. Start by reading, in order:

1. [CLAUDE.md](CLAUDE.md) — operating manual, domain invariants, code practices
2. [STATUS.md](STATUS.md) — current phase, next task, blockers
3. [docs/PLAN.md](docs/PLAN.md) — the full phased build plan
4. [CHANGELOG.md](CHANGELOG.md) / [DECISIONS.md](DECISIONS.md) — history & rationale

## North star

Beat the book on soft prop markets, measured by **CLV and calibration** over
50+ logged bets — not by short-term profit. Flat small stakes; discipline is
encoded in config/settings.yaml and CLAUDE.md invariants.
