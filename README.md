# MagicLight Auto 🪄

<div align="center">

![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python)
![Playwright](https://img.shields.io/badge/playwright-1.40%2B-green?style=for-the-badge)
![FFmpeg](https://img.shields.io/badge/FFmpeg-4.4%2B-orange?style=for-the-badge)
![Version](https://img.shields.io/badge/version-v2.0.3-brightgreen?style=for-the-badge)

**Automated kids story video pipeline**
MagicLight.ai generation → FFmpeg processing → Google Drive upload → Sheets tracking

</div>

---

## What It Does

1. Reads pending stories from a Google Sheet
2. Logs into MagicLight.ai and generates the video automatically
3. Downloads the video + thumbnail
4. Applies logo overlay, trims the outro, appends your endscreen (FFmpeg)
5. Uploads everything to Google Drive
6. Writes Drive links and status back to the sheet

---

## Three Modes

| Mode | Workflow | What Happens |
|------|----------|-------------|
| **Complete** | `complete.yml` | Generate + Process + Upload → Status = Done |
| **Generate Only** | `generate.yml` | Login → Generate → Download → Upload raw video |
| **Process Only** | `process.yml` | Download from Drive → FFmpeg → Upload processed video |

---

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/net2t/MagicLight-Auto.git
cd MagicLight-Auto
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `.env`

```bash
cp .env.sample .env
```

Fill in your `.env`:

```env
# ── MagicLight Account ──────────────────────────────
EMAIL=your@email.com
PASSWORD=yourpassword

# ── Google Sheets ───────────────────────────────────
SHEET_ID=1MPfnJ2UajI-eKKqGS4y6eb3BEgXpJiZ44nr556cfXRE
SHEET_NAME=Database
CREDS_JSON=credentials.json

# ── Google Drive ────────────────────────────────────
DRIVE_FOLDER_ID=1KHQjJ7EfAxDtZCXgLxUNNdmM0uIfSfS2

# ── Video Processing ────────────────────────────────
LOGO_PATH=assets/logo.png
ENDSCREEN_VIDEO=assets/endscreen.mp4
TRIM_SECONDS=4
LOGO_X=7
LOGO_Y=5
LOGO_WIDTH=300
LOGO_OPACITY=1.0
ENDSCREEN_ENABLED=true
UPLOAD_TO_DRIVE=false

# ── Timing (increase on slow connections) ───────────
STEP1_WAIT=40
STEP2_WAIT=30
STEP3_WAIT=180
STEP4_RENDER_TIMEOUT=1200
```

### 3. Multi-Account (`accounts.txt`)

```
email1@gmail.com:Password1
email2@gmail.com:Password2
email3@gmail.com:Password3
```

One account per line. Script auto-rotates when credits fall below 70.

### 4. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **Google Sheets API** and **Google Drive API**
3. Create **Service Account** → Download JSON → rename to `credentials.json`
4. Share your Google Sheet with the service account email (`...@....iam.gserviceaccount.com`)
5. Share your Drive folder with the same service account email

### 5. Assets

Place these in the `assets/` folder:
- `logo.png` — your channel logo (PNG with transparency, ~300px wide)
- `endscreen.mp4` — your endscreen clip (5–10 seconds, 1920×1080)

---

## Local Usage

### Interactive Menu

```bash
python main.py
```

```
┌─────────────────────────────────────────┐
│  MagicLight Auto  v2.0.3                │
│  Complete Lifecycle Pipeline            │
└─────────────────────────────────────────┘

  Pending stories: 5

  1. Complete Run   — Generate + Process + Upload
  2. Generate Only  — MagicLight video creation
  3. Process Only   — Trim / Logo / Endscreen
  4. Loop Run       — Infinite loop (1 per cycle)
  5. Cleanup        — Clear output folder
  6. Health Check
  7. Exit

Select [1-7]:
```

After selecting mode → enter quantity → Drive upload Y/N.

### Command Line

```bash
# Generate 3 stories, upload to Drive, headless browser
python main.py --mode generate --max 3 --upload-drive --headless

# Full pipeline, 1 story
python main.py --mode combined --max 1 --upload-drive --headless

# Process only (videos already downloaded)
python main.py --mode process --upload-drive

# Infinite loop mode
python main.py --mode combined --loop --upload-drive --headless

# Debug verbose output
python main.py --mode generate --max 1 --debug --headless

# Fix sheet headers (run once on new sheet)
python main.py --migrate-schema
```

---

## GitHub Actions (Cloud)

### Required Secrets

Go to your repo → **Settings → Secrets and variables → Actions**

| Secret | Value |
|--------|-------|
| `ACCOUNTS_TXT` | Full contents of `accounts.txt` (one account per line: `email:password`) |
| `CREDENTIALS_JSON` | Full contents of `credentials.json` (Service Account JSON) |
| `SHEET_ID` | Your Google Sheet ID from the URL |
| `SHEET_NAME` | Tab name (usually `Database`) |
| `DRIVE_FOLDER_ID` | Google Drive folder ID |

**`ACCOUNTS_TXT` format for multi-account:**
```
account1@gmail.com:Password123
account2@gmail.com:Password456
account3@yahoo.com:Password789
```
Paste this directly into the secret value. Each line = one account. The workflow writes it to `accounts.txt` automatically on every run.

### Running Workflows

Go to **Actions tab → select workflow → Run workflow**:

- **Mode 1 — Generate Only**: Choose stories count + Drive toggle
- **Mode 2 — Process Only**: Reads `Drive_Link` from sheet, processes, re-uploads
- **Mode 3 — Complete**: Full pipeline in one run

### Scheduled Local Run (Windows)

The included `run_scheduled.bat` + `setup_schedule.ps1` set up an hourly Windows Task Scheduler job:

```bash
# Run once to create the scheduled task
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
```

This runs `main.py --mode generate --max 10 --upload-drive --headless` every hour.

---

## Google Sheet Structure

Your `Database` tab must have these **18 columns in order**:

| Col | Name | Written By | Description |
|-----|------|-----------|-------------|
| A | `Status` | Both | Pending → Processing → Generated → Done / Error |
| B | `Theme` | You | Story theme |
| C | `Title` | You | Story title |
| D | `Story` | You | Full story text |
| E | `Moral` | You | Story moral |
| F | `Gen_Title` | Generate | AI-generated title from MagicLight |
| G | `Gen_Summary` | Generate | AI-generated summary |
| H | `Gen_Tags` | Generate | AI-generated hashtags |
| I | `Drive_Link` | Generate | Raw video Drive link ← written after Mode 1 |
| J | `DriveImg_Link` | Generate | Thumbnail Drive link |
| K | `Project_URL` | Generate | MagicLight project URL |
| L | `Credit_Before` | Generate | Credits before generation |
| M | `Credit_After` | Generate | Credits after generation |
| N | `Email_Used` | Generate | Which account was used |
| O | `Notes` | Both | Status notes / error info |
| P | `Created_Time` | Generate | Generation start timestamp |
| Q | `Completed_Time` | Both | Last completion timestamp |
| R | `Process_D_Link` | Process | Processed video Drive link ← written after Mode 2/3 |

**Status Lifecycle:**
```
Pending → Processing → Generated → Done
                     ↘ No_Video
                     ↘ Error
                     ↘ Low Credit
```

> Run `python main.py --migrate-schema` once to write correct headers to your sheet.

---

## File Naming

```
output/
  row34-Generated-Lio_and_the_Sunflower/
    row34-Generated-Lio_and_the_Sunflower.mp4       ← raw video
    row34-Generated-Lio_and_the_Sunflower_thumb.jpg  ← thumbnail
    row34-Processed-Lio_and_the_Sunflower.mp4        ← after FFmpeg
```

---

## FFmpeg Profiles (`profiles.json`)

| Profile | Resolution | CRF | Preset | Best For |
|---------|-----------|-----|--------|----------|
| `youtube_standard` | 1080p | 23 | fast | **Default — good balance** |
| `default` | 1080p | 23 | veryfast | Fastest encoding |
| `youtube_high_quality` | 1080p | 18 | slow | Best quality (slow) |
| `no_logo` | 1080p | 23 | fast | Skip logo overlay |

Switch profile via `.env` or pass directly in code.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `SHEET_ID not set` | Add to `.env` |
| `credentials.json not found` | Download from Google Cloud Console |
| `FFmpeg not found` | Install FFmpeg, add to system PATH |
| `playwright install` error | Run `playwright install-deps chromium` first |
| Sheet not updating | Run `python main.py --migrate-schema` |
| Drive upload skipped | Set `DRIVE_FOLDER_ID` in `.env` |
| Status stuck on Processing | v2.0.3 fixes this — pull latest |
| Low Credit error | Add more accounts to `accounts.txt` |

### Debug Mode

```bash
python main.py --mode generate --max 1 --debug --headless
```

---

## Changelog

### v2.0.3 — Sheet Write Guaranteed (April 11, 2026)
- `Drive_Link` written **immediately** after video upload — before thumbnail
- `Process_D_Link` extraction fixed for all filename formats via `extract_row_num()`
- Layer guard removed — all schema columns always writable
- Status always updated even when Drive upload fails
- `process_video()` returns exact output path matching `process_all()` expectation

### v2.0.2 — Critical Bug Fixes (April 11, 2026)
- Fixed Drive_Link sheet updates after video generation
- Fixed "already done" false positives in process mode
- Fixed process workflow download from Google Drive
- Added YouTube standard profile to profiles.json

### v2.0.1 — Loop Mode & Branch Cleanup (April 10, 2026)
- Unified to `main` branch
- Fixed FFmpeg `output_file` undefined error
- Fixed Google Sheets 16-column limit error
- Loop mode with 30-second cooldown

### v2.0.0 — Major Update (April 9, 2026)
- Loop Mode, improved filename format
- Status lifecycle: Pending → Processing → Generated → Done
- Multi-account rotation from `accounts.txt`

### v1.0.0 — First Stable Release (April 6, 2026)
- Core automation working end-to-end
- Magic Thumbnail acquisition
- Credits worksheet auto-creation

---

## License

MIT License
