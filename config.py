"""
config.py — MagicLight Auto v3.0
=================================
Central configuration: all environment variables, pipeline constants,
directory paths, and logging setup.

Imported by all other modules as:
    from config import *
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# ── Version ───────────────────────────────────────────────────────────────────
__version__ = "3.0.0"

# ── MagicLight Credentials ────────────────────────────────────────────────────
EMAIL    = os.getenv("EMAIL", "")
PASSWORD = os.getenv("PASSWORD", "")

# ── Google Sheets ─────────────────────────────────────────────────────────────
SHEET_ID   = os.getenv("SHEET_ID", "")
SHEET_NAME = os.getenv("SHEET_NAME", "Database")
CREDS_JSON = os.getenv("CREDS_JSON", "credentials.json")

# ── Google Drive (optional utility only) ──────────────────────────────────────
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")

# ── YouTube ───────────────────────────────────────────────────────────────────
YOUTUBE_OAUTH_FILE       = os.getenv("YOUTUBE_OAUTH_FILE", "youtube_oauth.json")
YOUTUBE_TOKEN_FILE       = os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
YOUTUBE_DEFAULT_CATEGORY = os.getenv("YOUTUBE_DEFAULT_CATEGORY", "27")   # 27 = Education
YOUTUBE_DEFAULT_PRIVACY  = os.getenv("YOUTUBE_DEFAULT_PRIVACY", "public")

# ── Pipeline Mode ─────────────────────────────────────────────────────────────
# "local"   — generate + process, save locally only
# "youtube" — generate + process + upload to YouTube + update sheet
# "multi"   — same as youtube (structured for future expansion)
PIPELINE_MODE = os.getenv("PIPELINE_MODE", "local").lower()

# ── Pipeline Timing ───────────────────────────────────────────────────────────
STEP1_WAIT     = int(os.getenv("STEP1_WAIT",  "60"))
STEP2_WAIT     = int(os.getenv("STEP2_WAIT",  "30"))
STEP3_WAIT     = int(os.getenv("STEP3_WAIT", "180"))
RENDER_TIMEOUT = int(os.getenv("STEP4_RENDER_TIMEOUT", "1200"))
POLL_INTERVAL  = 10
RELOAD_INTERVAL = 120

# ── Output Directories ────────────────────────────────────────────────────────
OUT_BASE  = "output"
OUT_SHOTS = os.path.join(OUT_BASE, "screenshots")

# Temp pipeline directories
TEMP_DIR       = Path("temp")
DOWNLOADS_DIR  = TEMP_DIR / "downloads"
PROCESSED_DIR  = TEMP_DIR / "processed"
LOGS_DIR       = Path("logs")

# ── Video / FFmpeg ────────────────────────────────────────────────────────────
MAGICLIGHT_OUTPUT = Path(os.getenv("MAGICLIGHT_OUTPUT", OUT_BASE))
LOGO_PATH         = Path(os.getenv("LOGO_PATH",   "assets/logo.png"))
ENDSCREEN_VIDEO   = Path(os.getenv("ENDSCREEN_VIDEO", "assets/endscreen.mp4"))

TRIM_SECONDS      = int(os.getenv("TRIM_SECONDS",   "4"))
LOGO_X            = int(os.getenv("LOGO_X",         "7"))
LOGO_Y            = int(os.getenv("LOGO_Y",         "5"))
LOGO_WIDTH        = int(os.getenv("LOGO_WIDTH",     "300"))
LOGO_OPACITY      = float(os.getenv("LOGO_OPACITY", "1.0"))
ENDSCREEN_ENABLED = os.getenv("ENDSCREEN_ENABLED", "true").lower() == "true"
ENDSCREEN_DURATION = os.getenv("ENDSCREEN_DURATION", "auto")

# Legacy Drive flag — kept for --upload-drive CLI compatibility
UPLOAD_TO_DRIVE      = os.getenv("UPLOAD_TO_DRIVE", "false").lower() == "true"
LOCAL_OUTPUT_ENABLED = os.getenv("LOCAL_OUTPUT_ENABLED", "true").lower() == "true"

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "magiclight-dashboard-secret")
DASHBOARD_HOST       = os.getenv("DASHBOARD_HOST", "127.0.0.1")

# ── Debug ─────────────────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "0") == "1"

# ── Status Constants ─────────────────────────────────────────────────────────
STATUS_PENDING    = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_GENERATED  = "GENERATED"
STATUS_PROCESSED  = "PROCESSED"
STATUS_UPLOADED   = "UPLOADED"
STATUS_ERROR      = "ERROR"
STATUS_LOW_CREDIT = "LOW_CREDIT"
STATUS_NO_VIDEO   = "NO_VIDEO"

# For backward compat — sheet stores Title Case values
STATUS_MAP = {
    "pending":    "Pending",
    "processing": "Processing",
    "generated":  "Generated",
    "processed":  "Processed",
    "uploaded":   "Uploaded",
    "error":      "Error",
}

VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv'}

# ── Platform fix ──────────────────────────────────────────────────────────────
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

# ── Directory Bootstrap ───────────────────────────────────────────────────────
def ensure_dirs():
    """Create all required runtime directories."""
    dirs = [TEMP_DIR, DOWNLOADS_DIR, PROCESSED_DIR, LOGS_DIR]
    if LOCAL_OUTPUT_ENABLED:
        dirs += [Path(OUT_BASE), Path(OUT_SHOTS)]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

ensure_dirs()

# ── Central Logger ────────────────────────────────────────────────────────────
def _get_logger(name: str = "magiclight") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    # File handler
    log_file = LOGS_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"
    try:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)
    except Exception:
        pass
    return logger

log = _get_logger()
