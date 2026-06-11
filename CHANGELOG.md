# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Newest entries on top.
Every working session must add at least one entry under `[Unreleased]`.

## [Unreleased]

### Added
- 2026-06-12: Match-stats pipeline — ESPN JSON API ingest (corners, cards,
  fouls, shots, possession, referee) for WC 2018/2022, Euro 2024, Copa 2024
  and WC 2026 live, with permanent finished-only caching and strict parsers
  (unknown status enums and unmatched teams raise); referee card-rate table;
  `wc26 data scrape|sync` commands; automatic syncing of finished WC26
  results into the patch layer with ±1-day UTC-date tolerance. Manual stats
  entry now records yellows/reds separately.

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
