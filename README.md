# MagicLight v2.0

Automated children's video generation pipeline using **VideoGen**, **FFmpeg**, **YouTube API**, and **Google Sheets** as the source of truth.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env .env.local   # edit SHEET_ID and other values

# Run individual stages
python run.py --mode generate
python run.py --mode process
python run.py --mode upload --upload-youtube

# Run full pipeline
python run.py --mode combined --max 5 --headless

# Loop continuously
python run.py --mode combined --loop
```

## CLI Flags

| Flag | Description |
|------|-------------|
| `--mode` | `generate` / `process` / `upload` / `combined` |
| `--max N` | Max jobs per run (default: 5) |
| `--headless` | Browser headless mode |
| `--loop` | Loop every 60s |
| `--upload-youtube` | Upload to YouTube |
| `--upload-drive` | Upload to Google Drive |
| `--dry-run` | Simulate without sheet writes |
| `--debug` | Verbose logging + screenshots |
| `--check-credits` | Report account credits |
| `--migrate-schema` | Write headers to Sheet tabs |

## Sheet Tabs

| Tab | Purpose |
|-----|---------|
| `INPUT` | Source rows (Make.com) |
| `VideoGen` | Post-generation tracking |
| `Process` | Post-FFmpeg tracking |
| `YouTube` | Upload results |
| `Credits` | Account credit log |

## File Naming

```
{YYYYMMDDHHMMSS}_{slug-title}.mp4
Example: 20260425143055_my-kids-story.mp4
```

## Credentials Setup

| File | Location |
|------|----------|
| Google Sheets SA | `credentials/common/service_account.json` |
| VideoGen accounts | `credentials/generate/magilight_accounts.txt` |
| YouTube OAuth | `credentials/upload/youtube_oauth.json` |
| Drive Service | `credentials/upload/drive_service.json` |

## Docs

- [`docs/PLAN.md`](docs/PLAN.md) — System plan
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Technical design
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — Version history
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — Current progress
