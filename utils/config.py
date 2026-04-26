"""
MagicLight v2.0 — Configuration
Loads all environment variables and defines system-wide constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_RAW       = BASE_DIR / "output" / "raw"
OUTPUT_PROCESSED = BASE_DIR / "output" / "processed"
OUTPUT_THUMBNAILS= BASE_DIR / "output" / "thumbnails"
LOGS_DIR         = BASE_DIR / "logs"

CRED_COMMON      = BASE_DIR / "credentials" / "common"
CRED_GENERATE    = BASE_DIR / "credentials" / "generate"
CRED_UPLOAD      = BASE_DIR / "credentials" / "upload"

# Ensure output dirs exist
for _d in [OUTPUT_RAW, OUTPUT_PROCESSED, OUTPUT_THUMBNAILS, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─── Google Sheets ────────────────────────────────────────────────────────────
SHEET_ID = os.getenv("SHEET_ID", "YOUR_GOOGLE_SHEET_ID")

# Tab names — STRICT
TAB_INPUT    = "Phase1"
TAB_VIDEOGEN = "Phase2"
TAB_PROCESS  = "Phase3"
TAB_YOUTUBE  = "Phase4"
TAB_CREDITS  = "Credits"

SERVICE_ACCOUNT_FILE = CRED_COMMON / "service_account.json"

# ─── Credential Paths ─────────────────────────────────────────────────────────
ACCOUNTS_FILE        = CRED_GENERATE / "magilight_accounts.txt"
PLAYWRIGHT_SESSION   = CRED_GENERATE / "playwright_session.json"
DRIVE_SERVICE_FILE   = CRED_UPLOAD   / "drive_service.json"
YOUTUBE_OAUTH_FILE   = CRED_UPLOAD   / "youtube_oauth.json"
YOUTUBE_TOKEN_FILE   = CRED_UPLOAD   / "token.json"

# ─── ID Format ────────────────────────────────────────────────────────────────
# Format: YYYYMMDDHHMMSS  (e.g. 20260425143055)
ID_FORMAT = "%Y%m%d%H%M%S"

# ─── Slug Rules ───────────────────────────────────────────────────────────────
SLUG_MAX_LEN = 50

# ─── Runtime Flags (overridden by CLI args) ───────────────────────────────────
DEFAULT_MAX_JOBS = int(os.getenv("MAX_JOBS", "5"))
HEADLESS         = os.getenv("HEADLESS", "true").lower() == "true"
DEBUG            = os.getenv("DEBUG", "false").lower() == "true"

# ─── VideoGen Site ────────────────────────────────────────────────────────────
VIDEOGEN_URL = os.getenv("VIDEOGEN_URL", "https://app.videogen.io")
