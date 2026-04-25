# MagicLight v2.0 — Architecture

## Directory Structure
```
MagicLight-2.0/
├── run.py                  # CLI entry point
├── utils/                  # Shared utilities
│   ├── config.py           # Env + constants
│   ├── logger.py           # System + per-job logging
│   ├── sheets.py           # Google Sheets client
│   └── helpers.py          # ID, slug, file naming
├── stages/
│   ├── generate/           # VideoGen automation (Playwright)
│   ├── process/            # FFmpeg video processing
│   └── upload/             # YouTube + Drive upload
├── credentials/
│   ├── common/             # service_account.json (Sheets)
│   ├── generate/           # Playwright session + accounts
│   └── upload/             # YouTube OAuth + Drive service
├── output/
│   ├── raw/                # Downloaded raw videos
│   ├── processed/          # FFmpeg-processed videos
│   └── thumbnails/         # Extracted thumbnails
├── logs/                   # system.log + job_{ID}.log
├── docs/                   # Documentation
└── assets/                 # logo.png, endscreen.mp4
```

## Data Flow
```
Make.com → INPUT tab (Status=Ready)
   ↓
generate.py (Playwright)
   ↓  Status=Generated, Trigger=PROCESS
VideoGen tab
   ↓
process.py (FFmpeg)
   ↓  Status=Processed, Trigger=UPLOAD
Process tab
   ↓
upload.py (YouTube API)
   ↓  Status=Done
YouTube tab
```

## Credential Rules
- Each stage only accesses its own credentials folder
- Common service account (Sheets) is shared by all stages
- Upload stage never reads generate credentials, and vice versa

## Idempotency
- Check `Status` before processing any row
- Skip rows already marked Generated/Processed/Done
- Never re-upload if YouTube_Link is already set
