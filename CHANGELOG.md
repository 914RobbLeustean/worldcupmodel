# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Newest entries on top.
Every working session must add at least one entry under `[Unreleased]`.

## [Unreleased]

### Added
- 2026-06-12: Phase 2 — Dixon-Coles goal engine (penaltyblog, time-decay +
  tier weights, neutral-venue handling, Elo-anchored shrinkage with the blend
  documented in docs/MODEL.md; extra-time rows excluded per D012/D014) and
  the walk-forward backtest harness (monthly refit grid, leak-free per-match
  Elo, Elo-only + de-vigged market baselines). Historical 1X2 odds ingest
  from football-data.co.uk + BetExplorer, cross-verified (D015) →
  market_odds.parquet (211 matches). Reality gates as tests: engine beats
  Elo (0.9952 vs 1.0120 log-loss), does NOT beat the market (0.9706 —
  leak-check), live 1X2 sane vs market across 71 WC26 fixtures (D016).
  New commands: `wc26 refit` (versioned params: fit date + git SHA + data
  cutoff), `wc26 predict --date` (1X2 + totals in <1 s), `wc26 backtest`.
  New deps: openpyxl, scipy (explicit), scipy-stubs (dev). Full report in
  docs/MODEL.md. First WC26 result ingested (Mexico 2-0 South Africa).
- 2026-06-12: Match-stats pipeline — ESPN JSON API ingest (corners, cards,
  fouls, shots, possession, referee) for WC 2018/2022, Euro 2024, Copa 2024
  and WC 2026 live, with permanent finished-only caching and strict parsers
  (unknown status enums and unmatched teams raise); referee card-rate table;
  `wc26 data scrape|sync` commands; automatic syncing of finished WC26
  results into the patch layer with ±1-day UTC-date tolerance. Manual stats
  entry now records yellows/reds separately.

### Fixed
- 2026-06-12: `wc26 data scrape --tournament X` no longer overwrites
  match_stats.parquet with only that tournament's rows (subset scrapes now
  merge with the existing table) and no longer crashes when a tournament has
  no finished matches yet (first match day). New alias: "D.R. Congo"
  (BetExplorer) → dr_congo.

### Changed
- 2026-06-12: FBref dropped as the stats source (Cloudflare-blocked, needs
  Chrome+Selenium) in favor of ESPN — D011. Extra-time contamination (D012)
  and cross-source date drift (D013) are now explicit, flagged invariants.
- 2026-06-11: Phase 1 data layer (most of it) — team registry for all 48
  qualified teams (groups verified vs the Dec 2025 final draw) with strict +
  lenient alias resolution; results ingest from the martj42 GitHub mirror
  (49,405 played matches 1872→2026-06-10, pandera-validated) with manual
  patch override; WC26 fixtures table (72 group matches, venues, altitude
  flags) derived from the same source; in-repo Elo with as-of-date snapshots
  for leak-free backtests (top-12 sanity-checked); `wc26 add-result` manual
  entry path and `wc26 data ingest|status|elo` commands. Decisions D008–D010.
- 2026-06-11: Phase 0 scaffold — git repo, uv project (Python 3.12, locked deps:
  penaltyblog 1.11, pandas 3.0, pandera, soccerdata, typer), docs system
  (CLAUDE.md, STATUS.md, DECISIONS.md, docs/), Makefile, `wc26` Typer CLI with
  stub commands, smoke tests.
