# MagicLight v2.0 — Changelog

## [2.0.0] - 2026-04-26

### Added
- Fully independent pipeline stages: `generate`, `process`, `upload`
- `run.py` control center with `--mode`, `--max`, `--headless`, `--loop`, `--dry-run`, `--debug`
- `--check-credits` command for account credit reporting
- `--migrate-schema` command for ensuring correct sheet headers
- ID format changed to `YYYYMMDDHHMMSS` (e.g. `20260425143055`)
- Slug max length: 50 characters
- Trigger-based progression: `PROCESS` → `UPLOAD` (one-way only)
- Per-job log files: `logs/job_{ID}.log`
- Isolated credential folders per stage

### Changed
- Sheet tabs renamed: `INPUT`, `VideoGen`, `Process`, `YouTube`, `Credits`
- File naming: `{ID}_{slug}.mp4`
- Output folders: `output/raw/`, `output/processed/`, `output/thumbnails/`
- Replaced monolithic `main.py` with modular stage architecture

### Removed
- Old monolithic `main.py` pipeline
- Old `R##_` prefix video naming
- `index.html` Flask dashboard (replaced by Sheet-based coordination)
