"""
MagicLight Auto — Kids Story Video Pipeline
===========================================
Version : 2.0.3  [Sheet Write Guaranteed]
Released: 2026-04-11
Repo    : https://github.com/0utLawzz/MagicLight-Auto

Three Modes:
  combined  — Generate → FFmpeg Process → Upload (full pipeline)
  generate  — Video generation only (MagicLight.ai automation)
  process   — FFmpeg post-processing only

Flags:
  --mode combined|generate|process
  --max N        Stories limit (0 = all pending)
  --upload-drive Upload to Google Drive
  --headless     Run browser without UI
  --loop         Infinite loop (1 story per cycle)
  --debug        Verbose debug logging
  --dry-run      Preview only, no encoding
  --migrate-schema  Write correct headers to sheet (run once)

Usage:
    python main.py                              # Interactive menu
    python main.py --mode combined --max 1      # Full pipeline, 1 story
    python main.py --mode generate --max 5 --upload-drive --headless
    python main.py --mode process --upload-drive
    python main.py --mode combined --loop --upload-drive --headless
    python main.py --migrate-schema
"""

__version__ = "2.1.0"

import re
import os
import sys
import time
from pathlib import Path
import subprocess
import signal
import warnings
import argparse
import json
import shutil

_has_rich = True
try:
    from rich.progress import (Progress, SpinnerColumn, TextColumn,
                                BarColumn, TimeElapsedColumn)
except ImportError:
    _has_rich = False

VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv'}
import requests
from datetime import datetime

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console(highlight=False, emoji=False)

DEBUG = os.getenv("DEBUG", "0") == "1"

def _step(label): 
    console.print(f"\n[bold cyan]🔧 {label}[/bold cyan]")

def _ok(msg):     console.print(f"  [bold green]✅[/bold green] {msg}")
def _warn(msg):   console.print(f"  [bold yellow]⚠️[/bold yellow]  {msg}")
def _err(msg):    console.print(f"  [bold red]❌[/bold red] {msg}")
def _info(msg):   console.print(f"  [dim]ℹ️[/dim] {msg}")
def _dbg(msg):
    if DEBUG: console.print(f"  [dim magenta]🐛[DBG] {msg}[/dim magenta]")

def _show_table(title: str, headers: list, rows: list, style="blue"):
    """Display a formatted table with icons"""
    table = Table(title=title, show_header=True, header_style=f"bold {style}")
    for header in headers:
        table.add_column(header, style=style, no_wrap=False)
    
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    
    console.print(table)

def _show_status_table(status_data: dict):
    """Show status dashboard with icons"""
    table = Table(title="📊 Status Dashboard", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_column("Status", style="yellow")
    
    for key, value in status_data.items():
        status_icon = "✅" if str(value).lower() in ['true', 'done', 'active'] else "❌" if str(value).lower() in ['false', 'error', 'inactive'] else "ℹ️"
        table.add_row(key, str(value), status_icon)
    
    console.print(table)

# ── Config ────────────────────────────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

EMAIL    = os.getenv("EMAIL", "")
PASSWORD = os.getenv("PASSWORD", "")

SHEET_ID        = os.getenv("SHEET_ID",   "")
SHEET_NAME      = os.getenv("SHEET_NAME", "Database")
CREDS_JSON      = os.getenv("CREDS_JSON", "credentials.json")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")

STEP1_WAIT     = int(os.getenv("STEP1_WAIT",            "45"))   # reduced: AI script gen usually <45s
STEP2_WAIT     = int(os.getenv("STEP2_WAIT",            "20"))   # reduced: cast gen usually <20s
STEP3_WAIT     = int(os.getenv("STEP3_WAIT",           "120"))   # reduced: storyboard usually <120s
RENDER_TIMEOUT = int(os.getenv("STEP4_RENDER_TIMEOUT", "900"))   # reduced: 15 min max render
POLL_INTERVAL  = 5   # reduced from 10 to 5 for faster progress detection
RELOAD_INTERVAL = 90  # reduced from 120 to 90

OUT_BASE  = "output"
OUT_SHOTS = os.path.join(OUT_BASE, "screenshots")

MAGICLIGHT_OUTPUT   = Path(os.getenv("MAGICLIGHT_OUTPUT", OUT_BASE))
LOGO_PATH           = Path(os.getenv("LOGO_PATH",   "assets/logo.png"))
ENDSCREEN_VIDEO     = Path(os.getenv("ENDSCREEN_VIDEO", "assets/endscreen.mp4"))

TRIM_SECONDS        = int(os.getenv("TRIM_SECONDS",   "4"))
LOGO_X              = int(os.getenv("LOGO_X",         "7"))
LOGO_Y              = int(os.getenv("LOGO_Y",         "5"))
LOGO_WIDTH          = int(os.getenv("LOGO_WIDTH",     "300"))
LOGO_OPACITY        = float(os.getenv("LOGO_OPACITY", "1.0"))
ENDSCREEN_ENABLED   = os.getenv("ENDSCREEN_ENABLED",  "true").lower() == "true"
ENDSCREEN_DURATION  = os.getenv("ENDSCREEN_DURATION", "auto")
UPLOAD_TO_DRIVE     = os.getenv("UPLOAD_TO_DRIVE", "false").lower() == "true"
LOCAL_OUTPUT_ENABLED = os.getenv("LOCAL_OUTPUT_ENABLED", "true").lower() == "true"

_shutdown = False
_browser  = None

def close_browser():
    """Close the browser cleanly."""
    global _browser
    if _browser:
        try:
            _info("[browser] Closing browser...")
            # Fixed: Ensure all contexts are properly closed
            contexts_to_close = list(_browser.contexts)  # Copy list to avoid modification during iteration
            for context in contexts_to_close:
                try:
                    pages_to_close = list(context.pages)  # Copy list
                    for page in pages_to_close:
                        try:
                            if not page.is_closed():
                                page.close()
                        except Exception as page_e:
                            _dbg(f"[browser] Error closing page: {page_e}")
                    if not context.is_closed():
                        context.close()
                except Exception as ctx_e:
                    _dbg(f"[browser] Error closing context: {ctx_e}")
            if not _browser.is_connected():
                _browser.close()
            _browser = None
            _ok("[browser] Browser closed")
        except Exception as e:
            _warn(f"[browser] Error closing browser: {e}")
            _browser = None  # Force reset even on error

def _sig(sig, frame):
    global _shutdown, _browser
    _warn("[STOP] Ctrl+C — cleaning up...")
    _shutdown = True
    close_browser()
    import os as _os
    _os._exit(1)

signal.signal(signal.SIGINT, _sig)

if LOCAL_OUTPUT_ENABLED:
    for _d in [OUT_BASE, OUT_SHOTS]:
        os.makedirs(_d, exist_ok=True)
else:
    _info("[config] Local output disabled — files will not be saved locally")

# ── Google Sheets ─────────────────────────────────────────────────────────────
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

_gc    = None
_ws    = None
_hdr   = []
_cws   = None
CREDIT_PER_GEN = 60
_credits_total = 0
_credits_used  = 0

SHEET_SCHEMA: dict[str, int] = {
    "Status":           1,   # A
    "Theme":            2,   # B
    "Title":            3,   # C
    "Story":            4,   # D
    "Moral":            5,   # E
    "Gen_Title":        6,   # F
    "Gen_Summary":      7,   # G
    "Gen_Tags":         8,   # H
    "Project_URL":      9,   # I
    "Created_Time":    10,   # J
    "Completed_Time":  11,   # K
    "Notes":           12,   # L
    "Drive_Link":      13,   # M
    "DriveImg_Link":   14,   # N
    "Credit_Before":   15,   # O
    "Credit_After":    16,   # P
    "Email_Used":      17,   # Q
    "Credit_Acct":     18,   # R
    "Credit_Total":    19,   # S
    "Credit_Used":     20,   # T
    "Credit_Remaining": 21,
    "Process_D_Link":  22,  # U
    "YouTube_Link":    23,   # V — YouTube video URL after upload
}

LAYER_COLS: dict[str, set] = {
    "generation": set(SHEET_SCHEMA.keys()),
    "video":      set(SHEET_SCHEMA.keys()),
    "processing": set(SHEET_SCHEMA.keys()),
    "credit":     set(SHEET_SCHEMA.keys()),
}

def _get_service_account_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ]
    if not os.path.exists(CREDS_JSON):
        raise FileNotFoundError(f"Service account credentials not found: {CREDS_JSON}")
    return ServiceAccountCredentials.from_service_account_file(CREDS_JSON, scopes=scopes)

def _get_oauth_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ]
    oauth_file = "oauth_credentials.json"
    if not os.path.exists(oauth_file):
        raise FileNotFoundError(f"OAuth credentials file not found: {oauth_file}")
    token_file = "token.json"
    creds = None
    if os.path.exists(token_file):
        try:
            from google.auth.transport.requests import Request
            creds = Credentials.from_authorized_user_file(token_file, scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(oauth_file, scopes)
        creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    return creds

def _get_credentials():
    try:
        if os.path.exists("oauth_credentials.json"):
            return _get_oauth_credentials()
    except:
        pass
    return _get_service_account_credentials()

def _get_drive_credentials():
    """
    Get credentials for Google Drive uploads.
    Preference order:
      1. OAuth token.json (refreshable, has user storage quota) — preferred
      2. oauth_credentials.json flow (requires browser on first run)
      3. Service Account (fallback — has NO storage of its own, must use Shared Drive)
    On GitHub Actions, token.json is injected via OAUTH_TOKEN secret.
    """
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ]
    # Priority 1: Load directly from token.json (works on GitHub Actions)
    token_file = "token.json"
    if os.path.exists(token_file):
        try:
            from google.auth.transport.requests import Request
            creds = Credentials.from_authorized_user_file(token_file, scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                with open(token_file, 'w') as f:
                    f.write(creds.to_json())
            if creds and creds.valid:
                _dbg("[drive] Using OAuth token.json credentials")
                return creds
        except Exception as e:
            _warn(f"[drive] token.json load failed: {e}")
    # Priority 2: Full OAuth flow (requires oauth_credentials.json + browser on 1st run)
    try:
        if os.path.exists("oauth_credentials.json"):
            return _get_oauth_credentials()
    except Exception as e:
        _warn(f"[drive] OAuth flow failed: {e}")
    # Priority 3: Service Account (may fail on Drive upload if not Shared Drive)
    _warn("[drive] Falling back to Service Account — Drive upload may fail if not using Shared Drive")
    return _get_service_account_credentials()

def _get_sheet():
    global _gc, _ws, _hdr
    if _ws is not None:
        return _ws
    if not SHEET_ID:
        raise ValueError(f"SHEET_ID not set in .env (cwd={os.getcwd()}, env_path={_ENV_PATH})")
    creds = _get_credentials()
    _gc = gspread.authorize(creds)
    sh = _gc.open_by_key(SHEET_ID)
    _ws = sh.worksheet(SHEET_NAME)
    _hdr = _ws.row_values(1)
    return _ws

def ensure_credits_sheet():
    global _gc, _cws
    if _cws is not None:
        return _cws
    _get_sheet()
    sh = _gc.open_by_key(SHEET_ID)
    try:
        _cws = sh.worksheet("Credits")
    except Exception:
        _info("[credits] Creating Credits sheet...")
        _cws = sh.add_worksheet(title="Credits", rows="500", cols="10")
        _cws.update("A1:G1", [["Email", "Total_Credits", "Used_Credits",
                                "Remaining", "Last_Checked",
                                "Log_Timestamp", "Log_Detail"]])
        _ok("[credits] Credits sheet created")
    return _cws

def _read_credits_from_page(page):
    try:
        credit_selectors = [
            ".home-top-navbar-credit-amount",
            ".credit-amount",
            "[class*='credit']",
        ]
        credit_text = None
        for selector in credit_selectors:
            try:
                credit_element = page.locator(selector).first
                if credit_element.is_visible(timeout=2000):
                    credit_text = credit_element.inner_text().strip()
                    if credit_text and any(c.isdigit() for c in credit_text):
                        break
            except:
                continue
        if credit_text:
            clean_text = credit_text.replace(',', '')
            credit_match = re.search(r'(\d+)', clean_text)
            if credit_match:
                return int(credit_match.group(1)), 0
        return 0, 0
    except Exception as e:
        _warn(f"Error reading credits: {e}")
        return 0, 0

def _update_credits_login(email, total):
    try:
        ws = ensure_credits_sheet()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = ws.get_all_values()
        found_row = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0].strip().lower() == email.strip().lower():
                found_row = i
                break
        data = [email, str(total), "", "", now_str]
        if found_row:
            ws.update(f"A{found_row}:E{found_row}", [data])
        else:
            ws.append_row(data)
        return 0
    except Exception as e:
        _warn(f"[credits] Login update error: {e}")
        return 0

def _update_credits_completion(email, total, used, row_num, action, status):
    # Fixed: Add thread safety and validation
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with _sheet_update_lock:  # Prevent concurrent credit updates
                ws = ensure_credits_sheet()
                remaining = max(0, total - used)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Validate inputs
                if not email or not isinstance(email, str):
                    _warn(f"[credits] Invalid email: {email}")
                    return
                
                if not isinstance(total, (int, float)) or total < 0:
                    _warn(f"[credits] Invalid total credits: {total}")
                    return
                
                if not isinstance(used, (int, float)) or used < 0:
                    _warn(f"[credits] Invalid used credits: {used}")
                    return
                
                rows = ws.get_all_values()
                found_row = None
                
                # Search for existing email row
                for i, row in enumerate(rows[1:], start=2):
                    if row and len(row) > 0 and row[0].strip().lower() == email.strip().lower():
                        found_row = i
                        break
                
                detail = f"{action} | Row:{row_num} | Status:{status}"
                
                if found_row:
                    # Update existing row
                    try:
                        ws.update(f"C{found_row}:G{found_row}",
                                  [[str(used), str(remaining), now_str, detail]])
                        _dbg(f"[credits] Updated existing row {found_row} for {email}")
                    except Exception as update_e:
                        raise Exception(f"Failed to update row {found_row}: {update_e}")
                else:
                    # Append new row
                    try:
                        data = [email, str(total), str(used), str(remaining), now_str, now_str, detail]
                        ws.append_row(data)
                        _dbg(f"[credits] Added new row for {email}")
                    except Exception as append_e:
                        raise Exception(f"Failed to append row: {append_e}")
                
                return  # Success, exit retry loop
                
        except Exception as e:
            if attempt < max_retries - 1:
                _warn(f"[credits] Update attempt {attempt + 1} failed: {e}, retrying...")
                sleep_log(2 ** attempt, f"credits retry {attempt + 1}")
                # Force reconnection
                global _cws, _gc
                _cws = None
                _gc = None
            else:
                _err(f"[credits] All update attempts failed for {email}: {e}")
                break

def check_all_accounts_credits(headless=False):
    """
    Check all accounts from accounts.txt and log their credit data to the Credits sheet.
    This function iterates through all accounts, logs in to each, reads the credit balance,
    and logs the data to the 'Credits' tab in the Google Sheet.
    
    Args:
        headless: If True, run browser in headless mode (no UI)
    """
    global _browser
    
    _step("[Credits Check] Starting account credit check...")
    
    # Load accounts from accounts.txt
    accounts = []
    if os.path.exists("accounts.txt"):
        with open("accounts.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    u, p = line.split(":", 1)
                    accounts.append((u.strip(), p.strip()))
    
    if not accounts:
        if EMAIL and PASSWORD:
            accounts = [(EMAIL, PASSWORD)]
            _info("[Credits Check] Using single account from .env")
        else:
            _err("[Credits Check] No credentials in accounts.txt or .env")
            return
    
    _ok(f"[Credits Check] Loaded {len(accounts)} account(s)")
    
    # Initialize browser if not already running
    if _browser is None:
        _info(f"[Credits Check] Starting browser (headless={headless})...")
        playwright = sync_playwright().start()
        _browser = playwright.chromium.launch(headless=headless)
    
    checked_count = 0
    failed_count = 0
    
    for idx, (email, password) in enumerate(accounts, 1):
        _info(f"[Credits Check] Checking account {idx}/{len(accounts)}: {email}")
        
        try:
            # Create new context and page for this account
            context = _browser.new_context(accept_downloads=True, no_viewport=True)
            page = context.new_page()
            
            # Login using existing login function
            login(page, custom_email=email, custom_pw=password)
            
            # Navigate to user-center to read credits
            _info("[Credits Check] Navigating to user-center...")
            try:
                page.goto("https://magiclight.ai/user-center", timeout=45000)
                wait_site_loaded(page, None, timeout=30)
                sleep_log(2, "user center settle")
            except Exception as e:
                _warn(f"[Credits Check] Could not load user center: {e}")
            
            # Read credits using existing function
            total_credits, used_credits = _read_credits_from_page(page)
            
            _ok(f"[Credits Check] {email}: Total={total_credits}, Used={used_credits}")
            
            # Log to Credits sheet using existing function
            _update_credits_login(email, total_credits)
            
            # Logout and cleanup
            try:
                _logout(page)
            except:
                pass
            
            context.close()
            checked_count += 1
            
        except Exception as e:
            _err(f"[Credits Check] Failed for {email}: {e}")
            failed_count += 1
            try:
                context.close()
            except:
                pass
    
    _ok(f"[Credits Check] Complete: {checked_count} checked, {failed_count} failed")

def _col(name: str) -> int | None:
    return SHEET_SCHEMA.get(name)

def read_sheet():
    ws = _get_sheet()
    return ws.get_all_records(head=1)

def _actual_sheet_cols() -> set:
    """Return set of column names that actually exist in row 1 of the sheet."""
    try:
        ws = _get_sheet()
        return set(h.strip() for h in _hdr if h.strip())
    except:
        return set(SHEET_SCHEMA.keys())

import threading
_sheet_update_lock = threading.Lock()

def update_sheet_row(sheet_row_num: int, layer: str | None = None, **kw):
    # Fixed: Add thread safety and retry logic
    if not kw:
        return
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with _sheet_update_lock:  # Prevent concurrent writes
                ws = _get_sheet()
                actual_cols = _actual_sheet_cols()
                
                # Validate all columns before writing
                valid_updates = []
                for col_name, value in kw.items():
                    col_idx = _col(col_name)
                    if col_idx is None:
                        _dbg(f"[sheet] IGNORED unknown column '{col_name}'")
                        continue
                    if col_name not in actual_cols:
                        _dbg(f"[sheet] SKIPPED '{col_name}' — not in sheet headers")
                        continue
                    valid_updates.append((col_name, col_idx, value))
                
                if not valid_updates:
                    _warn(f"[sheet] No valid columns to update for row {sheet_row_num}")
                    return
                
                # Batch update all valid columns
                for col_name, col_idx, value in valid_updates:
                    try:
                        ws.update_cell(sheet_row_num, col_idx, str(value) if value is not None else "")
                        _dbg(f"[sheet] Row {sheet_row_num} col '{col_name}'({col_idx}) = '{str(value)[:40]}'")
                    except Exception as cell_e:
                        _warn(f"[sheet] Cell update failed for {col_name}: {cell_e}")
                        continue
                
                return  # Success, exit retry loop
                
        except Exception as e:
            if attempt < max_retries - 1:
                _warn(f"[sheet] Update attempt {attempt + 1} failed: {e}, retrying...")
                sleep_log(2 ** attempt, f"sheet retry {attempt + 1}")
                # Force reconnection on retry
                global _ws, _gc
                _ws = None
                _gc = None
            else:
                _err(f"[sheet] All update attempts failed for row {sheet_row_num}: {e}")
                break

def ensure_sheet_schema():
    ws = _get_sheet()
    headers = [""] * max(SHEET_SCHEMA.values())
    for name, idx in SHEET_SCHEMA.items():
        headers[idx - 1] = name
    end_col = chr(ord('A') + len(headers) - 1)
    ws.update(f"A1:{end_col}1", [headers])
    _ok(f"[schema] Headers written to row 1 (A–{end_col})")

def upload_to_drive(file_path, folder_name=None, max_retries=3):
    # Fixed: Add comprehensive error handling and retry logic
    file_path = str(file_path)
    if not file_path or not os.path.exists(file_path):
        _warn(f"[drive] File not found: {file_path}")
        return ""
    if not DRIVE_FOLDER_ID:
        _warn("[drive] DRIVE_FOLDER_ID not set — skipping upload")
        return ""
    
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > 5000:  # 5GB limit
        _warn(f"[drive] File too large ({file_size_mb:.1f}MB): {file_path}")
        return ""
    
    if not folder_name:
        folder_name = Path(file_path).stem.replace('_processed', '').replace('_thumb', '')
    
    _info(f"[drive] Uploading {os.path.basename(file_path)} ({file_size_mb:.1f}MB)...")
    
    for attempt in range(max_retries):
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            creds = _get_drive_credentials()  # OAuth preferred (avoids SA quota error)
            service = build('drive', 'v3', credentials=creds)
            
            # Create or find folder
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [DRIVE_FOLDER_ID]
            }
            
            try:
                resp = service.files().list(
                    q=f"name='{folder_name}' and '{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder'",
                    fields='files(id,name)'
                ).execute()
                folder_id = resp['files'][0]['id'] if resp.get('files') else None
            except Exception as list_e:
                _dbg(f"[drive] Folder list failed: {list_e}")
                folder_id = None
            
            if not folder_id:
                try:
                    folder = service.files().create(body=folder_metadata, fields='id').execute()
                    folder_id = folder.get('id')
                    _dbg(f"[drive] Created folder: {folder_id}")
                except Exception as create_e:
                    raise Exception(f"Failed to create folder: {create_e}")
            
            # Upload file with progress tracking
            file_metadata = {
                'name': os.path.basename(file_path), 
                'parents': [folder_id]
            }
            
            media = MediaFileUpload(
                file_path, 
                resumable=True,
                chunksize=1024*1024  # 1MB chunks
            )
            
            request = service.files().create(
                body=file_metadata, 
                media_body=media,
                fields='id, webViewLink'
            )
            
            # Handle resumable upload
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    _dbg(f"[drive] Upload progress: {progress}%")
                
                if _shutdown:  # Handle graceful shutdown
                    _warn("[drive] Upload interrupted by shutdown")
                    return ""
            
            link = response.get('webViewLink', '')
            if link:
                _ok(f"[drive] Uploaded -> {link}")
                return link
            else:
                raise Exception("No webViewLink in response")
                
        except Exception as e:
            if attempt < max_retries - 1:
                _warn(f"[drive] Upload attempt {attempt + 1} failed: {e}, retrying...")
                sleep_log(5 + (2 ** attempt), f"drive retry {attempt + 1}")
            else:
                _err(f"[drive] All upload attempts failed: {e}")
                return ""

# ── YouTube Config (read from .env) ───────────────────────────────────────────
YOUTUBE_TOKEN_FILE      = os.getenv("YOUTUBE_TOKEN_FILE",      "youtube_token.json")
YOUTUBE_CLIENT_FILE     = os.getenv("YOUTUBE_CLIENT_FILE",     "youtube_oauth.json")
YOUTUBE_DEFAULT_PRIVACY  = os.getenv("YOUTUBE_DEFAULT_PRIVACY",  "public")
YOUTUBE_DEFAULT_CATEGORY = os.getenv("YOUTUBE_DEFAULT_CATEGORY", "27")  # 27 = Education


def _get_youtube_credentials():
    """
    Load or refresh YouTube OAuth credentials.
    
    How it works:
    - First tries to load saved token from YOUTUBE_TOKEN_FILE (youtube_token.json)
    - If token expired → refreshes it automatically using refresh_token
    - If no token at all → starts browser OAuth flow (only needed ONCE on local machine)
    - On GitHub Actions: YOUTUBE_TOKEN secret is written to youtube_token.json by workflow
    
    Scopes needed:
    - youtube.upload → to upload videos
    - youtube → to read channel info
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    # YouTube needs its own separate OAuth scope — cannot reuse Drive/Sheets token
    YT_SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube"
    ]

    creds = None

    # ── Step 1: Try loading saved token ──────────────────────────────────────
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, YT_SCOPES)
            _dbg(f"[youtube] Loaded token from {YOUTUBE_TOKEN_FILE}")
        except Exception as e:
            _warn(f"[youtube] Could not load token file: {e}")
            creds = None

    # ── Step 2: Refresh if expired ────────────────────────────────────────────
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token back to file
            with open(YOUTUBE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            _dbg("[youtube] Token refreshed and saved")
        except Exception as e:
            _warn(f"[youtube] Token refresh failed: {e}")
            creds = None

    # ── Step 3: Full OAuth flow (only on local machine, first time) ───────────
    if not creds or not creds.valid:
        if not os.path.exists(YOUTUBE_CLIENT_FILE):
            raise FileNotFoundError(
                f"YouTube OAuth client file not found: {YOUTUBE_CLIENT_FILE}\n"
                f"Download from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs"
            )
        _info(f"[youtube] Starting OAuth flow — browser will open once...")
        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_FILE, YT_SCOPES)
        # port=0 = pick any free port automatically
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        # Save token for future runs (this is what you copy to GitHub Secret)
        with open(YOUTUBE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        _ok(f"[youtube] Token saved to {YOUTUBE_TOKEN_FILE}")
        _info(f"[youtube] IMPORTANT: Copy contents of {YOUTUBE_TOKEN_FILE} to GitHub Secret YOUTUBE_TOKEN")

    return creds


def upload_to_youtube(
    video_path,
    title,
    description="",
    tags=None,
    category_id=None,
    privacy=None,
    thumbnail_path=None,
    max_retries=3
):
    """
    Upload a video to YouTube using the YouTube Data API v3.

    Args:
        video_path     : str or Path — local path to the .mp4 file
        title          : str — YouTube video title (max 100 chars)
        description    : str — video description (max 5000 chars)
        tags           : list of str — YouTube tags (optional)
        category_id    : str — YouTube category ID (default from .env = "27" Education)
        privacy        : str — "public" / "unlisted" / "private" (default from .env)
        thumbnail_path : str or Path — optional .jpg/.png thumbnail to set after upload
        max_retries    : int — how many times to retry on failure

    Returns:
        str — YouTube video URL like https://youtube.com/watch?v=XXXX
              or "" if upload failed
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    # ── Validate file ─────────────────────────────────────────────────────────
    video_path = str(video_path)
    if not os.path.exists(video_path):
        _err(f"[youtube] Video file not found: {video_path}")
        return ""

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if file_size_mb > 128 * 1024:  # YouTube max = 128GB
        _err(f"[youtube] File too large: {file_size_mb:.0f}MB")
        return ""

    # ── Apply defaults ────────────────────────────────────────────────────────
    if not category_id:
        category_id = YOUTUBE_DEFAULT_CATEGORY   # "27" = Education by default
    if not privacy:
        privacy = YOUTUBE_DEFAULT_PRIVACY         # "public" by default
    if not tags:
        tags = []

    # Truncate title/description to YouTube limits
    title       = str(title)[:100]
    description = str(description)[:5000]

    _step(f"[youtube] Uploading: {os.path.basename(video_path)}")
    _info(f"[youtube] Size: {file_size_mb:.1f}MB | Privacy: {privacy} | Category: {category_id}")

    for attempt in range(max_retries):
        try:
            # ── Build YouTube API client ──────────────────────────────────────
            creds   = _get_youtube_credentials()
            youtube = build("youtube", "v3", credentials=creds)

            # ── Video metadata ────────────────────────────────────────────────
            body = {
                "snippet": {
                    "title":       title,
                    "description": description,
                    "tags":        tags,
                    "categoryId":  category_id,
                },
                "status": {
                    "privacyStatus":          privacy,
                    "selfDeclaredMadeForKids": False,  # Set True if channel is for kids
                }
            }

            # ── Media upload — resumable (handles large files + retries) ──────
            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=5 * 1024 * 1024  # 5MB chunks — good balance for GitHub Actions
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            # ── Upload with progress display ──────────────────────────────────
            response   = None
            last_pct   = -1
            while response is None:
                if _shutdown:
                    _warn("[youtube] Upload interrupted by shutdown signal")
                    return ""
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct != last_pct and pct % 10 == 0:
                        _info(f"[youtube] Upload progress: {pct}%")
                        last_pct = pct

            # ── Extract video ID and build URL ────────────────────────────────
            video_id  = response.get("id", "")
            video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

            if not video_url:
                raise ValueError(f"YouTube returned no video ID. Response: {response}")

            _ok(f"[youtube] Uploaded! → {video_url}")

            # ── Set thumbnail (optional, non-fatal) ───────────────────────────
            # Note: thumbnail upload requires the channel to be verified
            if thumbnail_path and os.path.exists(str(thumbnail_path)):
                try:
                    _info("[youtube] Setting thumbnail...")
                    thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=thumb_media
                    ).execute()
                    _ok("[youtube] Thumbnail set")
                except Exception as te:
                    # Thumbnail fails if channel is not verified — non-fatal
                    _warn(f"[youtube] Thumbnail upload failed (non-fatal — channel may need verification): {te}")

            return video_url

        except Exception as e:
            err_str = str(e)

            # ── Handle quota exceeded (most common GitHub Actions failure) ────
            if "quotaExceeded" in err_str or "quota" in err_str.lower():
                _err("[youtube] YouTube API quota exceeded!")
                _err("[youtube] Quota resets at midnight Pacific Time (PT)")
                _err("[youtube] Free quota: 10,000 units/day. One upload = ~1600 units")
                return ""  # No point retrying quota errors

            # ── Handle auth errors ────────────────────────────────────────────
            if "invalid_grant" in err_str or "Token has been expired" in err_str:
                _warn("[youtube] Auth token expired — deleting saved token, will re-auth")
                if os.path.exists(YOUTUBE_TOKEN_FILE):
                    os.remove(YOUTUBE_TOKEN_FILE)
                if attempt < max_retries - 1:
                    continue  # Retry with fresh auth

            # ── General retry ─────────────────────────────────────────────────
            if attempt < max_retries - 1:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                _warn(f"[youtube] Attempt {attempt + 1} failed: {e}")
                _warn(f"[youtube] Retrying in {wait}s...")
                sleep_log(wait, f"youtube retry {attempt + 1}")
            else:
                _err(f"[youtube] All {max_retries} attempts failed: {e}")
                return ""

    return ""


def upload_story_to_youtube(story_title, gen_summary, gen_tags, video_path,
                             thumbnail_path=None, sheet_row_num=None):
    """
    High-level wrapper: upload one story video to YouTube and update Sheet.
    
    Called from process_video() or _run_pipeline_core() after FFmpeg is done.
    
    Args:
        story_title    : str — original story title from Sheet col C
        gen_summary    : str — AI-generated description from Sheet col G
        gen_tags       : str — comma-separated tags from Sheet col H
        video_path     : str or Path — processed video file
        thumbnail_path : str or Path — optional thumbnail
        sheet_row_num  : int — Sheet row to update with YouTube_Link

    Returns:
        str — YouTube URL or ""
    """
    if not os.path.exists(str(video_path)):
        _warn(f"[youtube] Video not found for upload: {video_path}")
        return ""

    # ── Build tags list from Sheet col H (comma separated) ───────────────────
    tags_list = []
    if gen_tags:
        tags_list = [t.strip() for t in str(gen_tags).split(",") if t.strip()]
    # Add default channel tags
    tags_list += ["kids stories", "bedtime stories", "children", "animated"]
    tags_list = list(dict.fromkeys(tags_list))[:500]  # YouTube max 500 chars total

    # ── Build description ─────────────────────────────────────────────────────
    desc = str(gen_summary) if gen_summary else str(story_title)
    desc += "\n\n#KidsStories #BedtimeStories #AnimatedStories"

    # ── Upload ────────────────────────────────────────────────────────────────
    yt_url = upload_to_youtube(
        video_path     = video_path,
        title          = story_title,
        description    = desc,
        tags           = tags_list,
        thumbnail_path = thumbnail_path
    )

    # ── Write YouTube_Link to Sheet immediately if upload succeeded ───────────
    if yt_url and sheet_row_num:
        try:
            update_sheet_row(
                sheet_row_num,
                YouTube_Link = yt_url,   # Column 23 — see SHEET_SCHEMA below
                Status       = "Done"    # Mark story complete
            )
            _ok(f"[sheet] Row {sheet_row_num} YouTube_Link written")
        except Exception as se:
            _warn(f"[sheet] YouTube_Link write failed: {se}")

    return yt_url


# ── HOW TO CALL upload_story_to_youtube() from your existing code ─────────────
#
# Inside process_video() or wherever you call upload_story_to_drive(), ADD this:
#
#   if args.upload_youtube:        # <-- new CLI flag added below
#       yt_url = upload_story_to_youtube(
#           story_title    = row.get("Title", ""),
#           gen_summary    = row.get("Gen_Summary", ""),
#           gen_tags       = row.get("Gen_Tags", ""),
#           video_path     = processed_video_path,
#           thumbnail_path = thumb_path,
#           sheet_row_num  = sheet_row_num
#       )
#
# ─────────────────────────────────────────────────────────────────────────────

def upload_story_to_drive(story_folder, safe_name, video_path, thumb_path,
                           sheet_row_num=None):
    result = {"folder_link": "", "video_link": "", "thumb_link": ""}

    if not DRIVE_FOLDER_ID:
        _warn("[drive] DRIVE_FOLDER_ID not set — skipping Drive upload")
        return result

    if not video_path or not os.path.exists(str(video_path)):
        _warn(f"[drive] Video file missing: {video_path}")
        return result

    _info(f"[drive] Creating Drive folder for {safe_name}...")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = _get_credentials()
        service = build('drive', 'v3', credentials=creds)

        folder_meta = {
            'name': safe_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [DRIVE_FOLDER_ID]
        }
        folder = service.files().create(body=folder_meta, fields='id,webViewLink').execute()
        folder_id   = folder.get('id')
        result["folder_link"] = folder.get('webViewLink', '')
        _ok(f"[drive] Folder created -> {result['folder_link']}")

        _info("[drive] Uploading video...")
        vid_meta  = {'name': os.path.basename(str(video_path)), 'parents': [folder_id]}
        vid_media = MediaFileUpload(str(video_path), resumable=True)
        vid_file  = service.files().create(body=vid_meta, media_body=vid_media,
                                            fields='id,webViewLink').execute()
        result["video_link"] = vid_file.get('webViewLink', '')
        _ok(f"[drive] Video uploaded -> {result['video_link']}")

        # Write Drive_Link to sheet IMMEDIATELY after video upload
        if sheet_row_num:
            try:
                update_sheet_row(
                    sheet_row_num,
                    Drive_Link=result["video_link"],
                    Notes=f"Video uploaded to Drive"
                )
                _ok(f"[sheet] Row {sheet_row_num} Drive_Link written")
            except Exception as se:
                _warn(f"[sheet] Drive_Link write failed: {se}")

        # Thumbnail upload — optional, failure does not block
        if thumb_path and os.path.exists(str(thumb_path)):
            try:
                _info("[drive] Uploading thumbnail...")
                thumb_meta  = {'name': os.path.basename(str(thumb_path)), 'parents': [folder_id]}
                thumb_media = MediaFileUpload(str(thumb_path), resumable=True)
                thumb_file  = service.files().create(body=thumb_meta, media_body=thumb_media,
                                                      fields='id,webViewLink').execute()
                result["thumb_link"] = thumb_file.get('webViewLink', '')
                _ok(f"[drive] Thumbnail uploaded -> {result['thumb_link']}")
                if sheet_row_num and result["thumb_link"]:
                    try:
                        update_sheet_row(sheet_row_num, DriveImg_Link=result["thumb_link"])
                    except Exception as se:
                        _warn(f"[sheet] DriveImg_Link write failed: {se}")
            except Exception as te:
                _warn(f"[drive] Thumbnail upload failed (non-fatal): {te}")
        else:
            _info("[drive] No thumbnail to upload")

        _ok(f"[drive] Story upload complete!")
        return result

    except Exception as e:
        _warn(f"[drive] Drive upload failed: {e}")
        if result["video_link"] and sheet_row_num:
            try:
                update_sheet_row(sheet_row_num, Drive_Link=result["video_link"])
            except: pass
        return result

def story_dir(safe_name):
    d = os.path.join(OUT_BASE, safe_name)
    os.makedirs(d, exist_ok=True)
    return d

def cleanup_local_files_if_drive_only(story_folder, video_path=None, thumb_path=None):
    if os.environ.get("DRIVE_ONLY_MODE") == "true":
        _info("[Drive-only] Cleaning up local files...")
        try:
            if video_path and os.path.exists(str(video_path)):
                os.remove(str(video_path))
            if thumb_path and os.path.exists(str(thumb_path)):
                os.remove(str(thumb_path))
            if story_folder and os.path.exists(story_folder):
                for file in Path(story_folder).glob("*_processed.*"):
                    file.unlink()
                if not any(Path(story_folder).iterdir()):
                    shutil.rmtree(story_folder)
        except Exception as e:
            _warn(f"[Drive-only] Cleanup error: {e}")

# ── Sleep helpers ─────────────────────────────────────────────────────────────
def sleep_log(seconds, reason=""):
    secs = int(seconds)
    if secs <= 0: return
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {secs}s{label}...")
    for _ in range(secs):
        if _shutdown: return
        time.sleep(1)

def _wait_dismissing(page, seconds, reason=""):
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {seconds}s{label} (popup-watch)...")
    start = time.time()
    last_pct = ""
    while time.time() - start < seconds:
        if _shutdown: return
        pct = min(100, int((time.time() - start) / seconds * 100))
        if str(pct) != last_pct and pct % 5 == 0:
            console.print(f"  [cyan]>[/cyan] Waiting{label}... [bold]{pct}%[/bold]")
            last_pct = str(pct)
        _dismiss_all(page)
        time.sleep(1)

# ── Popup helpers ─────────────────────────────────────────────────────────────
def _all_frames(page):
    try: return page.frames
    except: return [page]

_CLOSE_SELECTORS = [
    'button.notice-popup-modal__close',
    'button[aria-label="close"]',
    'button[aria-label="Close"]',
    '.sora2-modal-close',
    'button:has-text("Got it")',
    'button:has-text("Got It")',
    'button:has-text("Later")',
    'button:has-text("Not now")',
    'button:has-text("No thanks")',
    '.notice-bar__close',
    '.arco-modal-close-btn',
    '.arco-icon-close',
    'button:has-text("Skip")',
    'button.close-btn',
    'span[class*="close"]'
]

_PROMO_CLOSE_JS = """\
() => {
    const promoClose = Array.from(document.querySelectorAll(
        '[class*="privilege-modal"] [class*="close"],' +
        '[class*="new-year"] [class*="close"],' +
        '[class*="promo"] [class*="close"],' +
        '[class*="upgrade"] [class*="close"],' +
        '.arco-modal-close-btn'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    });
    if (promoClose.length) { promoClose[0].click(); return 'promo-closed'; }
    const svgBtns = Array.from(document.querySelectorAll(
        '.arco-modal .arco-modal-close-btn, .arco-modal-close-btn'
    )).filter(el => el.getBoundingClientRect().width > 0);
    if (svgBtns.length) { svgBtns[0].click(); return 'modal-x-closed'; }
    return null;
}"""

_POPUP_JS = """\
() => {
    const BAD = ["Got it","Got It","Close","Done","OK","Later","No thanks",
                 "Maybe later","Not now","Dismiss","Close samples","No","Skip"];
    let n = 0;
    document.querySelectorAll('button,span,div,a').forEach(el => {
        const t = (el.innerText || el.textContent || '').trim();
        if (BAD.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); n++; }
        }
    });
    document.querySelectorAll(
        '.arco-modal-mask,.driver-overlay,.diy-tour__mask,[class*="tour-mask"],[class*="modal-mask"]'
    ).forEach(el => { try { el.style.display='none'; } catch(e){} });
    return n;
}"""

def _dismiss_all(page):
    try:
        is_prog = page.evaluate("() => Array.from(document.querySelectorAll('[class*=\"progress\"],[class*=\"generating\"],[class*=\"Progress\"]')).some(el => el.getBoundingClientRect().width > 0)")
        if is_prog: return
    except: pass
    for fr in _all_frames(page):
        try: page.evaluate(_PROMO_CLOSE_JS)
        except: pass
        try: page.evaluate(_POPUP_JS)
        except: pass
        for sel in _CLOSE_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=1000)
            except: pass

def dismiss_popups(page, timeout=10, sweeps=3):
    for _ in range(sweeps):
        if _shutdown: return
        _dismiss_all(page)
        try: page.wait_for_timeout(800)
        except: time.sleep(0.8)

_REAL_DIALOG_JS = """\
() => {
    const masks = Array.from(document.querySelectorAll(
        '.arco-modal-mask,[class*="modal-mask"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 100;
    });
    if (!masks.length) return null;
    const chk = Array.from(document.querySelectorAll(
        'input[type="checkbox"],.arco-checkbox-icon,label[class*="checkbox"]'
    )).find(el => {
        const par = el.closest('label') || el.parentElement;
        const txt = ((par && par.innerText) || el.innerText || '').toLowerCase();
        return txt.includes('remind') || txt.includes('again') || txt.includes('ask');
    });
    if (chk) { try { chk.click(); } catch(e) {} }
    const xBtn = document.querySelector(
        '.arco-modal-close-btn,[aria-label="Close"],[aria-label="close"],' +
        '.arco-icon-close,[class*="modal-close"],[class*="close-icon"]'
    );
    if (xBtn && xBtn.getBoundingClientRect().width > 0) {
        xBtn.click(); return 'dialog: closed X';
    }
    const wrapper = document.querySelector('.arco-modal-wrapper');
    if (wrapper) {
        wrapper.remove();
        masks.forEach(m => m.remove());
        return 'dialog: removed wrapper';
    }
    return 'dialog: mask found but no X';
}"""

def _dismiss_animation_modal(page):
    try: page.evaluate(_PROMO_CLOSE_JS)
    except: pass
    try:
        r = page.evaluate(_REAL_DIALOG_JS)
        if r:
            _info(f"[modal] {r}")
            time.sleep(2); return
    except: pass
    for sel in ["label:has-text(\"Don't remind again\")", "label:has-text(\"Don't ask again\")"]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500); time.sleep(0.5)
        except: pass
    for sel in ['.arco-modal-close-btn', 'button[aria-label="Close"]', '.arco-icon-close']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=2000)
                time.sleep(2); return
        except: pass
    try: page.keyboard.press("Escape"); time.sleep(0.5)
    except: pass

def _wait_for_preview_page(page, timeout=60):
    _info("[post-render] Waiting for preview page...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        found = page.evaluate("""\
() => {
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    const dlBtn = Array.from(document.querySelectorAll('button,a')).find(el => {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        return r.width > 0 && (t === 'Download video' || t === 'Download Video');
    });
    if (items.length > 0 || dlBtn) return true;
    return false;
}""")
        if found:
            _ok("Preview page loaded")
            return True
        time.sleep(2)
    _warn("Preview page timeout")
    return False

def _handle_generated_popup(page):
    """
    Handle the post-generation popup that appears after video is ready.
    MagicLight shows a modal with 'Publish' + 'View' (or 'View video') buttons.
    We need to dismiss it (click 'View' / 'Not now') to reach the preview page.
    """
    _info("[post-render] Checking for generated popup...")

    # ── Step 1: Dismiss the Publish / View modal ─────────────────────────────
    # MagicLight shows: [Publish to Marketplace]  [View video] or [Not now]
    # Click 'View' / 'Not now' / 'Skip' to go to preview rather than publish.
    js_dismiss_publish = """\
() => {
    const PREFER = ['View video','View Video','View','Not now','Not Now','Skip','Cancel'];
    const AVOID  = ['Publish','publish'];
    // First try to find a dedicated dismiss button
    for (const txt of PREFER) {
        const all = Array.from(document.querySelectorAll('button,div[class*="btn"],a,span'));
        for (const el of all) {
            const t = (el.innerText || '').trim();
            const r = el.getBoundingClientRect();
            if (t === txt && r.width > 0 && r.height > 0) {
                el.click(); return 'clicked:' + txt;
            }
        }
    }
    // Fallback: close button / X on any visible modal
    const closes = Array.from(document.querySelectorAll(
        '.arco-modal-close-btn, button[aria-label="close"], button[aria-label="Close"],'
        + '.sora2-modal-close, [class*="modal-close"]'
    )).filter(el => el.getBoundingClientRect().width > 0);
    if (closes.length) { closes[0].click(); return 'modal-x'; }
    return null;
}"""

    deadline = time.time() + 20
    dismissed = False
    while time.time() < deadline:
        # Also handle legacy 'Submit' flow
        for sub_sel in ["button:has-text('Submit')", ".arco-modal button:has-text('Submit')"]:
            try:
                loc = page.locator(sub_sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    loc.first.click(); dismissed = True; break
            except: pass
        if dismissed: break
        r = page.evaluate(js_dismiss_publish)
        if r:
            _ok(f"[post-render] Popup dismissed: {r}")
            dismissed = True; break
        time.sleep(1.5)

    if dismissed:
        sleep_log(3, "post-popup settle")
        _wait_for_preview_page(page, timeout=30)

    # ── Step 2: Try clicking 'Download video' on preview page (optional fast-path)
    dl_deadline = time.time() + 20
    while time.time() < dl_deadline:
        for sel in [
            "button:text-is('Download video')",
            "a:text-is('Download video')",
            "div:text-is('Download video')",
            "button:text-is('Download Video')",
            "a:text-is('Download Video')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    loc.first.click()
                    _ok("[post-render] Download video clicked")
                    return True
            except: pass
        time.sleep(2)
    _warn("[post-render] Download video button not found in popup — will find via _download()")
    return False

# ── DOM helpers ───────────────────────────────────────────────────────────────
def wait_site_loaded(page, key_locator=None, timeout=60):
    try: page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
    except: pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        try:
            if page.evaluate("document.readyState") in ("interactive", "complete"):
                break
        except: pass
        time.sleep(0.3)
    if key_locator is not None:
        try:
            key_locator.wait_for(
                state="visible",
                timeout=max(1000, int((deadline - time.time()) * 1000))
            )
        except: return False
    return True

def dom_click_text(page, texts, timeout=60):
    js = """\
(texts) => {
    const all = Array.from(document.querySelectorAll(
        'button,div[class*="btn"],span[class*="btn"],a,' +
        'div[class*="vlog-btn"],div[class*="footer-btn"],' +
        'div[class*="shiny-action"],div[class*="header-left-btn"]'
    ));
    for (let i = all.length - 1; i >= 0; i--) {
        const el = all[i]; let dt = '';
        el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
        const t = dt.trim() || (el.innerText || '').trim();
        if (texts.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); return t; }
        }
    }
    return null;
}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        r = page.evaluate(js, texts)
        if r:
            _info(f"  '{r}'")
            return True
        time.sleep(2)
    return False

def dom_click_class(page, cls, timeout=30):
    js = f"""\
() => {{
    const all = Array.from(document.querySelectorAll('[class*="{cls}"]'));
    for (let i = all.length-1; i >= 0; i--) {{
        const el = all[i], r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {{ el.click(); return el.className; }}
    }}
    return null;
}}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        r = page.evaluate(js)
        if r: return True
        time.sleep(2)
    return False

def screenshot(page, name):
    path = os.path.join(OUT_SHOTS, f"{name}_{int(time.time())}.png")
    try: page.screenshot(path=path, full_page=True)
    except: pass
    return path

def debug_buttons(page):
    js = """\
() => Array.from(document.querySelectorAll(
    'button,div[class*="btn"],span[class*="btn"],a,div[class*="vlog-btn"]'
)).filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && (el.innerText || '').trim();
}).map(el =>
    el.tagName + '.' + el.className.substring(0, 40) +
    ' | ' + (el.innerText || '').trim().substring(0, 60)
);"""
    try:
        items = page.evaluate(js)
        _info(f"[debug-url] {page.url}")
        for i in (items or []): _info(f"  {i}")
    except: pass

def _credit_exhausted(page):
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        for kw in ["insufficient credits", "not enough credits", "out of credits",
                   "credits exhausted", "quota exceeded"]:
            if kw in body.lower():
                return True
    except: pass
    return False

# ── LOGIN ─────────────────────────────────────────────────────────────────────
def _logout(page):
    _info("   Clearing session...")
    try:
        page.goto("https://magiclight.ai/", timeout=30000)
        wait_site_loaded(page, None, timeout=20)
        time.sleep(2)
        page.evaluate("""\
() => {
    const logoutTexts = ['Log out','Logout','Sign out','Sign Out','Log Out'];
    const els = Array.from(document.querySelectorAll('a,button,div,span'));
    for (const el of els) {
        const t = (el.innerText || '').trim();
        if (logoutTexts.includes(t) && el.getBoundingClientRect().width > 0) {
            el.click(); return t;
        }
    }
    return null;
}""")
        time.sleep(1)
    except: pass
    try: page.context.clear_cookies()
    except: pass

def login(page, custom_email=None, custom_pw=None):
    # Fixed: Add comprehensive login validation and session verification
    _step("[Login] Starting fresh login...")
    
    email = custom_email or EMAIL
    password = custom_pw or PASSWORD
    
    if not email or not password:
        raise Exception("Login failed — missing credentials")
    
    try:
        page.context.clear_cookies()
        page.context.clear_permissions()
    except Exception as e:
        _dbg(f"[login] Cookie clear failed: {e}")
    
    _logout(page)
    
    # Navigate to login page with retry
    login_success = False
    for attempt in range(3):
        try:
            page.goto("https://magiclight.ai/login/?to=%252Fkids-story%252F", timeout=60000)
            wait_site_loaded(page, None, timeout=30)
            
            # Verify we're on login page
            if "login" in page.url.lower() or "magiclight.ai" in page.url:
                login_success = True
                break
            else:
                _warn(f"[login] Attempt {attempt + 1}: Not on login page: {page.url}")
                sleep_log(2, f"login retry {attempt + 1}")
        except Exception as nav_e:
            _warn(f"[login] Navigation attempt {attempt + 1} failed: {nav_e}")
            if attempt < 2:
                sleep_log(3, f"login retry {attempt + 1}")
    
    if not login_success:
        raise Exception("Login failed — could not navigate to login page")
    
    sleep_log(3, "page settle")
    dismiss_popups(page, timeout=5)
    
    # Click email tab with better detection
    clicked_email_tab = False
    for sel in ['.entry-email', 'text=Log in with Email',
                'button:has-text("Log in with Email")', '[class*="entry-email"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click(timeout=5000)
                clicked_email_tab = True
                sleep_log(3, "inputs settle")
                break
        except: pass
    
    if not clicked_email_tab:
        try:
            page.evaluate("""() => {
                const el = document.querySelector('.entry-email') ||
                           [...document.querySelectorAll('button')].find(b => b.innerText.includes('Email'));
                if (el) el.click();
            """)
            sleep_log(2)
        except Exception as js_e:
            _dbg(f"[login] JS email tab click failed: {js_e}")
    
    # Fill email with validation
    email_filled = False
    for sel in ['input[type="text"]', 'input[type="email"]', 'input[name="email"]',
                'input.arco-input', 'input[placeholder*="mail" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=15000)
            loc.scroll_into_view_if_needed()
            loc.click()
            page.wait_for_timeout(500)
            loc.fill(email)
            
            # Verify email was filled
            filled_value = loc.input_value()
            if email.lower() in filled_value.lower():
                email_filled = True
                _ok(f"[login] Email filled: {email[:10]}...")
                break
        except: continue
    
    if not email_filled:
        screenshot(page, "login_fail_no_email")
        raise Exception("Login failed — email input not found or not fillable")
    
    page.wait_for_timeout(500)
    
    # Fill password with validation
    pass_filled = False
    for sel in ['input[type="password"]', 'input[name="password"]',
                'input[placeholder*="password" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            loc.fill(password)
            
            # Verify password was filled (check length)
            filled_value = loc.input_value()
            if len(filled_value) >= len(password) * 0.8:  # Allow some tolerance
                pass_filled = True
                _ok("[login] Password filled")
                break
        except: continue
    
    if not pass_filled:
        raise Exception("Login failed — password input not found or not fillable")
    
    # Click continue with retry
    clicked = False
    for attempt in range(3):
        for sel in [".signin-continue", "text=Continue", "div.signin-continue",
                    "button:has-text('Continue')", "button.arco-btn-primary"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click(); clicked = True; break
            except: pass
        if clicked: break
        if attempt < 2:
            page.wait_for_timeout(2000)
    
    if not clicked:
        screenshot(page, "login_fail_no_continue")
        raise Exception("Login failed — Continue button not found")
    
    # Wait for redirect and verify login success
    try:
        page.wait_for_url("**/kids-story/**", timeout=30000)
        sleep_log(2)
        
        # Verify we're logged in by checking for logout options
        logout_found = page.evaluate("""() => {
            const logoutTexts = ['Log out','Logout','Sign out','Sign Out','Log Out'];
            const els = Array.from(document.querySelectorAll('a,button,div,span'));
            for (const el of els) {
                const t = (el.innerText || '').trim();
                if (logoutTexts.includes(t) && el.getBoundingClientRect().width > 0) {
                    return true;
                }
            }
            return false;
        }""")
        
        if not logout_found:
            _warn("[login] Login may have failed - no logout option found")
        else:
            _ok("[login] Login verified - logout option available")
            
    except Exception as redirect_e:
        _warn(f"[login] Redirect verification failed: {redirect_e}")
        page.wait_for_timeout(5000)
    
    _ok(f"[Login] Logged in -> {page.url}")
    page.wait_for_timeout(3000)
    dismiss_popups(page, timeout=10, sweeps=4)
    _ok("[Login] Post-login popups cleared")
    
    # Read credits with better error handling
    _step("[credits] Reading credits from User Center...")
    try:
        page.goto("https://magiclight.ai/user-center", timeout=45000)
        wait_site_loaded(page, None, timeout=30)
        
        # Wait for credit element with timeout
        credit_selector = ".home-top-navbar-credit-amount, .credit-amount"
        try:
            page.wait_for_selector(credit_selector, state="visible", timeout=15000)
        except:
            _warn("[credits] Credit selector not visible, trying alternative")
            
        sleep_log(2, "user center settle")
    except Exception as e:
        _warn(f"[credits] Could not load user center: {e}")
    
    global _credits_total, _credits_used
    total, used = _read_credits_from_page(page)
    if total > 0:
        _credits_total = total
        _update_credits_login(email, total)
        _ok(f"[credits] Credits available: {total}")
    else:
        _warn("[credits] Could not read credit count")
    
    try:
        page.goto("https://magiclight.ai/kids-story/", timeout=45000)
        wait_site_loaded(page, None, timeout=30)
    except Exception as final_e:
        _warn(f"[login] Final navigation failed: {final_e}")

# ── STEP 1: Story Input ───────────────────────────────────────────────────────
def step1(page, story_text):
    _step("[Step 1] Story input ->")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    wait_site_loaded(page, None, timeout=60)
    sleep_log(3, "initial page settle")
    dismiss_popups(page, timeout=10)
    
    # Find textarea with multiple fallback selectors
    ta = None
    for ta_sel in [
        page.get_by_role("textbox", name="Please enter an original"),
        page.locator("textarea.arco-textarea"),
        page.locator("textarea[placeholder*='enter']"),
        page.locator("textarea[placeholder*='story']"),
        page.locator("textarea"),
    ]:
        try:
            if hasattr(ta_sel, 'count'):
                if ta_sel.count() > 0 and ta_sel.first.is_visible(timeout=5000):
                    ta = ta_sel.first
                    break
            else:
                ta_sel.wait_for(state="visible", timeout=10000)
                ta = ta_sel
                break
        except: continue
    
    if ta is None:
        screenshot(page, "step1_no_textarea")
        raise Exception("[Step 1] Cannot find story textarea")
    
    dismiss_popups(page, timeout=6)
    ta.wait_for(state="visible", timeout=20000)
    ta.scroll_into_view_if_needed()
    ta.click()
    page.wait_for_timeout(500)
    ta.fill(story_text)
    _ok("Story text filled")
    sleep_log(2)
    
    # Select Pixar style with robust selector
    _click_style_option(page, "Pixar 2.0")
    sleep_log(1)
    
    # Select 16:9 aspect ratio with robust JS click
    _click_aspect_ratio(page, "16:9")
    sleep_log(1)
    
    # Scroll down to expose voiceover/music dropdowns
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(2)
    
    # Select voiceover – retry up to 3 times, verify female voice selected
    _select_dropdown_robust(page, "Voiceover", "Sophia", timeout_open=5, timeout_pick=3, retries=3)
    sleep_log(1)
    _select_dropdown_robust(page, "Background Music", "Silica", timeout_open=5, timeout_pick=3, retries=2)
    
    # Scroll again and click Next
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(1)
    clicked = False
    for sel in ["button.arco-btn-primary:has-text('Next')", "button:has-text('Next')",
                ".vlog-bottom", "div[class*='footer-btn']:has-text('Next')",
                "div[class*='shiny-action']:has-text('Next')",
                "div[class*='header-left-btn']:has-text('Next')"]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible(timeout=2000):
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step", "Continue"], timeout=20)
    if not clicked:
        screenshot(page, "step1_no_next")
        raise Exception("Step 1 Next button not found")
    _ok("Next -> Step 2")
    _wait_dismissing(page, STEP1_WAIT, "AI generating script")


def _click_style_option(page, style_text):
    """Click a style option (e.g. 'Pixar 2.0') using multiple selector strategies."""
    # Strategy 1: JS exact text match on visible elements
    result = page.evaluate("""
(style) => {
    const candidates = Array.from(document.querySelectorAll('div,span,button,label,li'));
    for (const el of candidates) {
        const ownText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim()).join('');
        const fullText = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if ((ownText === style || fullText === style) && r.width > 0 && r.height > 0) {
            ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'].forEach(e => 
                el.dispatchEvent(new MouseEvent(e, {bubbles:true, cancelable:true, view:window})));
            return style;
        }
    }
    return null;
}""", style_text)
    if result:
        _ok(f"Style: {style_text}")
        return True
    # Strategy 2: Playwright filter
    try:
        loc = page.locator("div,span").filter(has_text=re.compile(f"^{re.escape(style_text)}$")).first
        if loc.is_visible(timeout=3000):
            loc.click()
            _ok(f"Style: {style_text}")
            return True
    except: pass
    _warn(f"Style '{style_text}' not found — using default")
    return False


def _click_aspect_ratio(page, ratio_text):
    """Click aspect ratio button (e.g. '16:9') using JS for precision."""
    result = page.evaluate("""
(ratio) => {
    // Look for ratio buttons/labels - they're usually radio/tab style
    const selectors = [
        '[class*="ratio"]',
        '[class*="aspect"]',
        '[class*="resolution"]',
        'div.arco-radio-button',
        'span.arco-radio-button',
        'label[class*="radio"]',
        'div[class*="tab-item"]',
        'div[class*="option"]',
    ];
    for (const sel of selectors) {
        const els = Array.from(document.querySelectorAll(sel));
        for (const el of els) {
            const t = (el.innerText || el.textContent || '').trim();
            const r = el.getBoundingClientRect();
            if (t === ratio && r.width > 0 && r.height > 0) {
                ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'].forEach(e => 
                    el.dispatchEvent(new MouseEvent(e, {bubbles:true, cancelable:true, view:window})));
                return 'selector:' + sel;
            }
        }
    }
    // Fallback: find any element whose exact text is the ratio
    const all = Array.from(document.querySelectorAll('div,span,button,label'));
    for (const el of all) {
        const ownText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim()).join('');
        const r = el.getBoundingClientRect();
        if (ownText === ratio && r.width > 0 && r.height > 5) {
            ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'].forEach(e => 
                el.dispatchEvent(new MouseEvent(e, {bubbles:true, cancelable:true, view:window})));
            return 'fallback:ownText';
        }
    }
    return null;
}""", ratio_text)
    if result:
        _ok(f"Aspect ratio: {ratio_text} (via {result})")
        return True
    _warn(f"Aspect ratio '{ratio_text}' not found — using default")
    return False


def _select_dropdown_robust(page, label_text, option_text, timeout_open=5, timeout_pick=3, retries=3):
    """
    Robust dropdown selection with:
    - Multiple open strategies
    - Wait for options to appear after open
    - Verify selection was applied
    - Retry on failure
    """
    js_open = """
(label) => {
    // Find label element
    const all = Array.from(document.querySelectorAll('label,div,span,p,h4,h5'));
    for (const el of all) {
        if (el.getBoundingClientRect().width === 0) continue;
        const ownText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
        const fullText = (el.innerText || '').trim();
        if (ownText !== label && fullText !== label) continue;
        // Walk up to find the select trigger
        let c = el;
        for (let i = 0; i < 8; i++) {
            if (!c) break;
            const triggers = c.querySelectorAll(
                '.arco-select-view, .arco-select-view-input, ' +
                '[class*="select-view"], [class*="arco-select"], ' +
                '[class*="selector"], [class*="select-trigger"]'
            );
            for (const t of triggers) {
                const r = t.getBoundingClientRect();
                if (r.width > 0) {
                    ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'].forEach(e => 
                        t.dispatchEvent(new MouseEvent(e, {bubbles:true, cancelable:true, view:window})));
                    return label + ':found@' + i; 
                }
            }
            c = c.parentElement;
        }
    }
    // Fallback: find any arco-select near a label with the text
    const selects = Array.from(document.querySelectorAll('.arco-select, [class*="select-wrap"]'));
    for (const sel of selects) {
        const parent = sel.closest('[class*="form-item"], [class*="setting"], [class*="row"]');
        if (!parent) continue;
        const labelEl = parent.querySelector('label, [class*="label"]');
        if (labelEl && (labelEl.innerText || '').trim() === label && sel.getBoundingClientRect().width > 0) {
            const trigger = sel.querySelector('.arco-select-view, [class*="select-view"]');
            if (trigger && trigger.getBoundingClientRect().width > 0) { trigger.click(); return label + ':formitem'; }
            sel.click();
            return label + ':select-click';
        }
    }
    return null;
}"""
    js_pick = """
(opt) => {
    const simulateClick = (el) => {
        ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click'].forEach(e => {
            el.dispatchEvent(new MouseEvent(e, { bubbles: true, cancelable: true, view: window }));
        });
    };
    // Options are usually rendered in a portal/popup outside the main DOM
    const containers = [
        document.body,
        ...Array.from(document.querySelectorAll(
            '[class*="dropdown"], [class*="popup"], [class*="select-popup"], .arco-select-popup, [class*="option-list"]'
        ))
    ];
    for (const container of containers) {
        const items = Array.from(container.querySelectorAll(
            '.arco-select-option, [class*="select-option"], [class*="option-item"], ' +
            'li[class*="option"], [role="option"]'
        )).filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        for (const el of items) {
            const t = (el.innerText || el.textContent || '').trim();
            // exact match OR starts-with (handles 'Sophia (Adult)' style labels)
            if (t === opt || t.startsWith(opt)) {
                simulateClick(el);
                return t;
            }
        }
    }
    // Fallback: title attribute match
    for (const container of containers) {
        const items = Array.from(container.querySelectorAll('[title]')).filter(el => {
            const r = el.getBoundingClientRect();
            const t = (el.getAttribute('title') || '').trim();
            return r.width > 0 && r.height > 0 && (t === opt || t.startsWith(opt));
        });
        if (items.length > 0) { simulateClick(items[0]); return items[0].getAttribute('title'); }
    }
    return null;
}"""
    js_verify = """
(args) => {
    const [label, opt] = args;
    const all = Array.from(document.querySelectorAll('label,div,span,p,h4,h5'));
    for (const el of all) {
        if (el.getBoundingClientRect().width === 0) continue;
        const fullText = (el.innerText || '').trim();
        if (fullText !== label) continue;
        let c = el;
        for (let i = 0; i < 8; i++) {
            if (!c) break;
            const view = c.querySelector(
                '.arco-select-view, .arco-select-view-value, [class*="select-view"]'
            );
            if (view) {
                let txt = view.getAttribute('title') || view.innerText || view.textContent || '';
                // Also check child nodes if empty
                if (!txt.trim()) {
                    const valEl = view.querySelector('.arco-select-view-value');
                    if (valEl) txt = valEl.innerText || valEl.textContent || '';
                }
                const cln = txt.trim();
                if (cln) return cln.includes(opt) ? 'ok:' + cln : 'wrong:' + cln;
            }
            c = c.parentElement;
        }
    }
    return 'notfound';
}"""
    
    for attempt in range(retries):
        try:
            # Step 0: Scroll the dropdown area into view so it's clickable
            page.evaluate("""
(label) => {
    const all = Array.from(document.querySelectorAll('label,div,span,p,h4,h5'));
    for (const el of all) {
        const t = (el.innerText || '').trim();
        if (t === label && el.getBoundingClientRect().width > 0) {
            el.scrollIntoView({behavior:'smooth',block:'center'});
            return true;
        }
    }
    return false;
}""", label_text)
            time.sleep(0.3)

            # Step 1: Open the dropdown
            r = page.evaluate(js_open, label_text)
            if not r:
                _warn(f"[dropdown] '{label_text}' trigger not found (attempt {attempt+1})")
                sleep_log(2, f"dropdown retry {attempt+1}")
                continue
            _dbg(f"[dropdown] Opened '{label_text}': {r}")
            
            # Step 2: Wait for options to appear in the DOM
            options_appeared = False
            for _ in range(timeout_open * 2):  # poll every 500ms
                visible_options = page.evaluate("""
() => Array.from(document.querySelectorAll(
    '.arco-select-option, [class*="select-option"], [class*="option-item"], [role="option"]'
)).filter(el => el.getBoundingClientRect().height > 0).length
""")
                if visible_options > 0:
                    options_appeared = True
                    break
                time.sleep(0.5)
            
            if not options_appeared:
                _warn(f"[dropdown] Options did not appear for '{label_text}' (attempt {attempt+1})")
                page.keyboard.press("Escape")
                sleep_log(1)
                continue
            
            # Step 3: Pick the option
            time.sleep(0.5)  # settle before pick
            r2 = page.evaluate(js_pick, option_text)
            # Step 3b: Playwright native exact-text click as reinforcement
            try:
                pl_opt = page.locator(
                    '.arco-select-option, [class*="select-option"], [class*="option-item"], [role="option"]'
                ).filter(has_text=re.compile(f"^{re.escape(option_text)}")).first
                if pl_opt.count() > 0 and pl_opt.is_visible(timeout=1500):
                    pl_opt.click(timeout=3000)
                    r2 = option_text  # treat as picked
            except Exception:
                pass  # JS pick was enough
            if r2:
                # Give Vue/Arco MORE time to commit before verifying (was 1.2s)
                time.sleep(2.0)
                # Step 4: Verify the selection was applied
                verify = page.evaluate(js_verify, [label_text, option_text])
                if verify.startswith("ok:"):
                    _ok(f"[dropdown] {label_text} -> '{option_text}' (verified: {verify})")
                    return True
                elif verify.startswith("wrong:"):
                    _warn(f"[dropdown] Voiceover shows '{verify}' instead of '{option_text}' (attempt {attempt+1})")
                    if attempt == retries - 1:
                        # Last attempt: option WAS clicked, DOM verify is stale.
                        # Accept — the UI will use the correct voice.
                        _warn(f"[dropdown] Accepting '{option_text}' despite stale verify (last attempt)")
                        return True
                    try: page.keyboard.press("Escape")
                    except: pass
                    sleep_log(1.5)
                    continue
                else:
                    _ok(f"[dropdown] {label_text} -> '{option_text}' (unverified — {verify})")
                    return True
            else:
                _warn(f"[dropdown] Option '{option_text}' not found in '{label_text}' dropdown")
                # Log available options for debugging
                available = page.evaluate("""
() => Array.from(document.querySelectorAll(
    '.arco-select-option, [class*="select-option"], [class*="option-item"], [role="option"]'
)).filter(el => el.getBoundingClientRect().height > 0)
  .map(el => (el.innerText || '').trim()).slice(0, 20)
""")
                _info(f"[dropdown] Available options: {available}")
                page.keyboard.press("Escape")
                sleep_log(1)
                
        except Exception as e:
            _warn(f"[dropdown] Error on attempt {attempt+1}: {e}")
            try: page.keyboard.press("Escape")
            except: pass
            sleep_log(1)
    
    _warn(f"[dropdown] Failed to select '{option_text}' in '{label_text}' after {retries} attempts")
    return False


# Keep legacy _select_dropdown as thin wrapper for backward compat
def _select_dropdown(page, label_text, option_text):
    return _select_dropdown_robust(page, label_text, option_text, retries=2)

# ── STEP 2: Cast ──────────────────────────────────────────────────────────────
def step2(page):
    _step(f"[Step 2] Cast generation ({STEP2_WAIT}s)...")
    dismiss_popups(page, timeout=5)
    
    # Wait for cast/characters to load — detect when they're ready or timeout
    _info("[Step 2] Waiting for cast images to appear...")
    cast_wait_deadline = time.time() + STEP2_WAIT
    js_cast_ready = """
() => {
    const imgs = document.querySelectorAll('[class*="role"] img, [class*="cast"] img, [class*="character"] img');
    const loaded = Array.from(imgs).filter(i => i.naturalWidth > 0).length;
    return {total: imgs.length, loaded: loaded};
}"""
    while time.time() < cast_wait_deadline:
        if _shutdown: break
        _dismiss_all(page)
        try:
            cs = page.evaluate(js_cast_ready)
            if cs['total'] > 0 and cs['loaded'] >= cs['total']:
                _ok(f"[Step 2] Cast ready: {cs['loaded']}/{cs['total']} images")
                break
        except: pass
        time.sleep(3)
    
    # Extra dismissal pass
    dismiss_popups(page, timeout=5)
    sleep_log(2)
    
    # Click Next Step with extended selector list
    clicked = False
    for sel in [
        "div[class*='step2-footer-btn-left']",
        "button:has-text('Next Step')",
        "div[class*='footer']:has-text('Next Step')",
        "div[class*='header-shiny-action__btn']:has-text('Next Step')",
        "div[class*='header-left-btn']:has-text('Next Step')",
        "button.arco-btn-primary:has-text('Next Step')",
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible(timeout=2000):
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next Step", "Next", "Animate All"], timeout=20)
    sleep_log(3)
    _dismiss_animation_modal(page)
    sleep_log(2)
    _ok("[Step 2] Done")

# ── STEP 3: Storyboard ────────────────────────────────────────────────────────
def step3(page):
    _step(f"[Step 3] Storyboard (up to {STEP3_WAIT}s)...")
    dismiss_popups(page, timeout=5)
    js_img = """
() => {
    const imgs = document.querySelectorAll(
        '[class*="role-card"] img, [class*="scene"] img,' +
        '[class*="storyboard"] img, [class*="story-board"] img,' +
        '[class*="panel"] img, [class*="slide"] img'
    );
    const loaded = Array.from(imgs).filter(i => i.naturalWidth > 0 && i.src && !i.src.includes('data:image/gif')).length;
    return {total: imgs.length, loaded: loaded};
}"""
    deadline = time.time() + STEP3_WAIT
    last_log = 0
    while time.time() < deadline:
        if _shutdown: break
        try:
            cs = page.evaluate(js_img)
            if cs['loaded'] >= 2:
                _ok(f"[Step 3] Storyboard ready: {cs['loaded']}/{cs['total']} images")
                break
            if time.time() - last_log >= 15:
                _info(f"[step3] Waiting for storyboard: {cs['loaded']}/{cs['total']} images loaded")
                last_log = time.time()
        except: pass
        _dismiss_all(page)
        time.sleep(4)
    sleep_log(2)
    _set_subtitle_style(page)
    sleep_log(1)
    clicked = False
    for sel in [
        "[class*='header'] button:has-text('Next')",
        "[class*='header-shiny-action__btn']:has-text('Next')",
        "div[class*='header-left-btn']:has-text('Next')",
        "div[class*='step2-footer-btn-left']",
        "button.arco-btn-primary:has-text('Next')",
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible(timeout=2000):
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step"], timeout=15)
    
    sleep_log(3, "checking for Animate All popup")
    # Do NOT blindly dismiss here. Check for 'Animate All' first!
    js_animate = """() => {
        const btns = Array.from(document.querySelectorAll('button, div[class*="btn"]'));
        for (let b of btns) {
            const t = (b.innerText || '').trim();
             if (t === 'Animate All') {
                const r = b.getBoundingClientRect();
                if (r.width > 0) { b.click(); return true; }
             }
        }
        return false;
    }"""
    if page.evaluate(js_animate):
        _info("[Step 3] Clicked 'Animate All' for scenes. Waiting for scenes to animate...")
        start = time.time()
        last_pct = ""
        while time.time() - start < RENDER_TIMEOUT:
            if _shutdown: break
            prog_js = """() => {
                const prog = Array.from(document.querySelectorAll('[class*="progress"],[class*="Progress"],[class*="render-progress"],[class*="generating"]'))
                    .find(el => el.getBoundingClientRect().width > 0 && (el.innerText || '').match(/[0-9]+\\s*%/));
                if (prog) {
                    const m = (prog.innerText || '').match(/(\\d+)\\s*%/);
                    return m ? m[1] : null;
                }
                const chk = document.body.innerText || '';
                if (chk.includes('have been generated') || !chk.includes('generating')) return 'DONE';
                return null;
            }"""
            res = page.evaluate(prog_js)
            if res and res != "DONE" and res != last_pct:
                console.print(f"  [cyan]>[/cyan] Scenes Animating... [bold]{res}%[/bold]")
                last_pct = res
            elif res == "DONE" or (not res and last_pct == "100"):
                break
            time.sleep(POLL_INTERVAL)
            # Carefully clear popups but don't close important windows
            try: page.evaluate(_POPUP_JS)
            except: pass
            
        sleep_log(3, "scenes animated")
        _info("Clicking Next to proceed to Edit stage...")
        for _ in range(3):
            if dom_click_text(page, ["Next"], timeout=5): break
            time.sleep(2)
    else:
        _dismiss_animation_modal(page)
        
    sleep_log(3)
    _ok("[Step 3] Done")

def _set_subtitle_style(page):
    for txt in ["Subtitle Settings", "Subtitle", "Caption"]:
        try:
            t = page.locator(f"text='{txt}'")
            if t.count() > 0 and t.first.is_visible():
                t.first.click(); sleep_log(2); break
        except: pass
    result = page.evaluate("""\
() => {
    let items = Array.from(document.querySelectorAll('.coverFontList-item'));
    if (!items.length) items = Array.from(document.querySelectorAll(
        '[class*="coverFont"] [class*="item"],[class*="subtitle-item"]'
    ));
    const vis = items.filter(el => {
        const r = el.getBoundingClientRect(); return r.width > 5 && r.height > 5;
    });
    if (vis.length >= 10) { vis[9].click(); return 'subtitle style #10 set'; }
    return 'only ' + vis.length + ' items';
}""")
    _info(f"[step3] {result}")

# ── STEP 4: Navigate to Generate -> Wait -> Download ──────────────────────────
def step4(page, safe_name, sheet_row_num=None):
    _step("[Step 4] Navigating to Generate...")
    MAX_NEXT = 100
    js_modal_blocking = """\
() => {
    const masks = Array.from(document.querySelectorAll(
        '.arco-modal-mask,[class*="modal-mask"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 200 && r.height > 200;
    });
    if (masks.length) return 'mask';
    return null;
}"""
    js_header_next = """\
() => {
    if (typeof Node === 'undefined') return null;
    for (const el of Array.from(document.querySelectorAll(
        '[class*="header-shiny-action__btn"],[class*="header-left-btn"]'
    ))) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (t === 'Next' && r.width > 0) { el.click(); return 'header-shiny: Next'; }
    }
    for (const el of Array.from(document.querySelectorAll('button.arco-btn-primary'))) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (t === 'Next' && r.width > 0) { el.click(); return 'arco-primary: Next'; }
    }
    return null;
}"""
    js_has_gen = """\
() => {
    const texts = ["Generate","Create Video","Export","Create now","Render"];
    const all = Array.from(document.querySelectorAll(
        'button,div[class*="btn"],span[class*="btn"],div[class*="footer-btn"],' +
        'div[class*="header-shiny-action__btn"],[class*="animation-modal__tab"]'
    ));
    for (let i = all.length-1; i >= 0; i--) {
        const el = all[i]; let dt = '';
        el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
        const t = dt.trim() || (el.innerText || '').trim();
        if (texts.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return t + '|||' + el.className.substring(0,60);
        }
    }
    return null;
}"""
    for attempt in range(MAX_NEXT):
        _dismiss_animation_modal(page)
        sleep_log(2)
        try: page.screenshot(path="debug_step4.png")
        except: pass
        raw = page.evaluate(js_has_gen)
        if raw:
            found_text, found_cls = raw.split("|||", 1)
            _ok(f"Generate button found after {attempt} attempts: '{found_text}'")
            break
        blocking = page.evaluate(js_modal_blocking)
        if blocking:
            _warn(f"Modal blocking — re-dismissing")
            _dismiss_animation_modal(page)
            sleep_log(3)
            continue
        r = page.evaluate(js_header_next)
        _info(f"[step4] attempt {attempt+1}: {r or 'no header Next'}")
        if not r:
            debug_buttons(page)
        sleep_log(4)
    else:
        raise Exception("Could not reach Generate button after max attempts")
    if not dom_click_text(page, ["Generate", "Create Video", "Export",
                                  "Create now"], timeout=20):
        raise Exception("Generate click failed")
    sleep_log(3)
    dom_click_text(page, ["OK", "Ok", "Confirm"], timeout=5)
    sleep_log(3)
    _dismiss_all(page)
    _info(f"[Step 4] Waiting for render (max {RENDER_TIMEOUT//60} min)...")
    start = time.time(); last_reload = start; render_done = False
    js_state = r"""
() => {
    // 1. Progress bar / percentage indicator (highest priority - still rendering)
    const prog = Array.from(document.querySelectorAll(
        '[class*="progress"],[class*="Progress"],[class*="render-progress"],'
        + '[class*="generating"],[class*="loading-bar"],[class*="task-progress"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && (el.innerText || '').match(/[0-9]+\s*%/);
    });
    if (prog.length > 0) {
        const m = (prog[0].innerText || '').match(/(\d+)\s*%/);
        return 'progress:' + (m ? m[1] : '?') + '%';
    }
    // 2. "Download" button visibly available
    const dlTexts = ['Download video','Download Video','Download'];
    const btns = Array.from(document.querySelectorAll(
        'button, a, div[class*="btn"], a[href*=".mp4"], a[download]'
    ));
    for (const el of btns) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (r.width > 0 && dlTexts.includes(t)) return 'btn:' + t;
    }
    // 3. Check for direct video element
    const vid = document.querySelector(
        'video[src*=".mp4"], video source[src*=".mp4"], a[href*=".mp4"]'
    );
    if (vid && vid.src) return 'video:' + vid.src.substring(0, 80);
    // 4. Page text cues (generation complete messages)
    const body = (document.body && document.body.innerText) || '';
    const kws = ['video has been generated','generation complete',
                 'successfully generated','video is ready','has been generated',
                 'generation succeed','your video is done'];
    for (const k of kws)
        if (body.toLowerCase().includes(k.toLowerCase())) return 'text:' + k;
    return null;
}"""
    last_pct = ""
    stall_count = 0
    last_sig = None
    while time.time() - start < RENDER_TIMEOUT:
        if _shutdown: break
        elapsed = int(time.time() - start)
        if time.time() - last_reload >= RELOAD_INTERVAL:
            try:
                page.reload(timeout=30000, wait_until="domcontentloaded")
                wait_site_loaded(page, None, timeout=30)
                _dismiss_all(page)
                _info(f"[step4] Page reloaded at {elapsed}s")
            except Exception as e:
                _warn(f"Reload error: {e}")
            last_reload = time.time()
        _dismiss_all(page)
        try:
            if page.is_closed():
                _err("Page was closed during render wait - aborting")
                break
            sig = page.evaluate(js_state)
        except Exception as e:
            _warn(f"Page evaluation error: {e}")
            try:
                page.goto(page.url, timeout=30000)
                wait_site_loaded(page, None, timeout=30)
                _dismiss_all(page)
                sig = page.evaluate(js_state)
            except:
                _err("Cannot recover from page evaluation error - aborting")
                break
        if sig is None:
            stall_count += 1
            if elapsed % 20 == 0:
                _info(f"[step4] {elapsed//60}m{elapsed%60}s elapsed (waiting for render signal)")
            if stall_count >= 60:  # 60 * 5s = 5 minutes stall, try reload
                _warn("[step4] No render signal for 5min, forcing reload")
                try:
                    page.reload(timeout=30000, wait_until="domcontentloaded")
                    wait_site_loaded(page, None, timeout=30)
                    _dismiss_all(page)
                except: pass
                stall_count = 0
                last_reload = time.time()
        elif sig.startswith("progress:"):
            pct = sig.split(":", 1)[1]
            if pct != last_pct:
                console.print(f"  [cyan]>[/cyan] Rendering... [bold]{pct}[/bold]")
                last_pct = pct
            stall_count = 0
        else:
            _ok(f"Render done ({elapsed}s) -> {sig}")
            render_done = True; break
        time.sleep(POLL_INTERVAL)
    if not render_done:
        _warn("Render timeout — attempting download anyway")
    sleep_log(3, "UI settle")
    popup_visible = page.evaluate("""\
() => {
    const body = (document.body && document.body.innerText) || '';
    return body.includes('has been generated') && body.includes('Submit');
}""")
    if popup_visible or render_done:
        _handle_generated_popup(page)
        sleep_log(3, "post-submit settle")
        _wait_for_preview_page(page, timeout=45)
    sleep_log(2)
    return _download(page, safe_name, sheet_row_num=sheet_row_num)

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
def _download(page, safe_name, sheet_row_num=None):
    out = {"video": "", "thumb": "", "gen_title": "", "summary": "", "tags": ""}
    if LOCAL_OUTPUT_ENABLED:
        sdir = story_dir(safe_name)
    else:
        sdir = None
        _info("[download] Local output disabled — skipping local save")
    meta = page.evaluate("""\
() => {
    const result = { title: '', summary: '', hashtags: '' };
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    items.forEach(item => {
        const label = (item.querySelector('.previewer-new-body-right-item-header-title') || {}).innerText || '';
        const ta    = item.querySelector('textarea.arco-textarea');
        const val   = ta ? (ta.value || ta.innerText || '').trim() : '';
        const key   = label.trim().toLowerCase();
        if (key === 'title')    result.title    = val;
        if (key === 'summary')  result.summary  = val;
        if (key === 'hashtags') result.hashtags = val;
    });
    return result;
}""") or {}
    out["gen_title"] = meta.get("title", "")
    out["summary"]   = meta.get("summary", "")
    out["tags"]      = meta.get("hashtags", "")
    _info(f"[meta] Title='{out['gen_title'][:50]}'")
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": page.url}
    thumb_dest = os.path.join(sdir, f"{safe_name}_thumb.jpg") if sdir else None
    try:
        page.mouse.move(1000, 400)
        page.mouse.wheel(0, 3000)
        time.sleep(1)
        page.keyboard.press("PageDown")
        page.keyboard.press("PageDown")
        time.sleep(1)
        page.evaluate("""() => {
            document.querySelectorAll('*').forEach(el => {
                try {
                    const ov = window.getComputedStyle(el).overflowY;
                    if(ov === 'auto' || ov === 'scroll' || ov === 'overlay') {
                        if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
                    }
                } catch(e) {}
            });
            window.scrollTo(0, document.body.scrollHeight);
        }""")
        time.sleep(3)
    except Exception as e:
        _warn(f"[thumb] Scroll warning: {e}")
    thumb_url = page.evaluate("""\
() => {
    return new Promise(async (resolve) => {
        function findImages(wrapper) {
            const imgs = Array.from(wrapper.querySelectorAll('img[src]'));
            for (let img of imgs) {
                let s = img.src.toLowerCase();
                if ((s.startsWith('http') || s.startsWith('blob:') || s.startsWith('data:'))
                    && img.naturalWidth > 100
                    && !s.includes('avatar') && !s.includes('icon') && !s.includes('logo')) {
                    return img.src;
                }
            }
            return null;
        }
        let src = null;
        const dlBtn = document.querySelector('.show-cover-download');
        if (dlBtn) {
            let wrapper = dlBtn;
            for (let i = 0; i < 4; i++) {
                if (!wrapper) break;
                src = findImages(wrapper);
                if (src) break;
                wrapper = wrapper.parentElement;
            }
        }
        if (!src) {
            const titles = Array.from(document.querySelectorAll('div, span'));
            for (const el of titles) {
                if ((el.innerText || '').trim().toLowerCase() === 'magic thumbnail') {
                    let wrapper = el;
                    for (let i = 0; i < 4; i++) {
                        if (!wrapper) break;
                        src = findImages(wrapper);
                        if (src) break;
                        wrapper = wrapper.parentElement;
                    }
                    if (src) break;
                }
            }
        }
        if (!src) return resolve(null);
        if (src.startsWith('data:')) return resolve(src);
        try {
            const response = await window.fetch(src);
            const blob = await response.blob();
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = () => resolve(src);
            reader.readAsDataURL(blob);
        } catch(e) { resolve(src); }
    });
}""")
    if thumb_url:
        try:
            content_bytes = None
            if thumb_url.startswith("data:"):
                import base64
                header, encoded = thumb_url.split(",", 1)
                content_bytes = base64.b64decode(encoded)
            elif thumb_url.startswith("http"):
                r = requests.get(thumb_url, timeout=30)
                if r.status_code == 200:
                    content_bytes = r.content
            if content_bytes and len(content_bytes) > 5000:
                if thumb_dest:
                    with open(thumb_dest, "wb") as f: f.write(content_bytes)
                    out["thumb"] = thumb_dest
                    _ok(f"Thumbnail -> {thumb_dest} ({len(content_bytes)//1024} KB)")
                else:
                    _ok(f"Thumbnail downloaded ({len(content_bytes)//1024} KB) - local save skipped")
        except Exception as e:
            _warn(f"Thumbnail error: {e}")
    if not out["thumb"]:
        fallback_url = page.evaluate("""\
() => {
    const selectors = [
        '[class*="timeline"] img[src]',
        '[class*="storyboard"] img[src]',
        '[class*="scene"] img[src]',
        'img[src*="oss"][src]',
    ];
    for (const sel of selectors) {
        const imgs = Array.from(document.querySelectorAll(sel))
            .filter(i => i.src.startsWith('http') && i.naturalWidth >= 50);
        if (imgs.length) return imgs[0].src;
    }
    return null;
}""")
        if fallback_url:
            try:
                r = requests.get(fallback_url, timeout=30, cookies=cookies, headers=headers)
                if r.status_code == 200 and len(r.content) > 1000:
                    if thumb_dest:
                        with open(thumb_dest, "wb") as f: f.write(r.content)
                        out["thumb"] = thumb_dest
                        _ok(f"Thumbnail (fallback) -> {thumb_dest}")
                    else:
                        _ok(f"Thumbnail (fallback) downloaded ({len(r.content)//1024} KB) - local save skipped")
            except Exception as e:
                _warn(f"Thumbnail fallback error: {e}")
    video_dest = os.path.join(sdir, f"{safe_name}.mp4") if sdir else None
    try:
        cancel_btn = page.locator('button', has_text="Cancel")
        if cancel_btn.count() > 0 and cancel_btn.first.is_visible(timeout=1000):
            cancel_btn.first.click(timeout=1000)
            sleep_log(1)
    except: pass
    _info("[dl] Waiting for video/download element (max 90s)...")
    vid_wait_deadline = time.time() + 90
    
    # Comprehensive JS to find video URL or download link
    js_find_dl = """
() => {
    // Priority 1: direct mp4 video element
    const v = document.querySelector('video[src*=".mp4"], video source[src*=".mp4"]');
    if (v && v.src) return {type: 'video', url: v.src};
    // Priority 2: anchor download link
    const anchors = Array.from(document.querySelectorAll('a[href*=".mp4"], a[download]'));
    for (const a of anchors) {
        const r = a.getBoundingClientRect();
        if (a.href && r.width >= 0) return {type: 'link', url: a.href};
    }
    // Priority 3: Download video button (visible)
    const dlTexts = ['Download video', 'Download Video', 'Download'];
    const btns = Array.from(document.querySelectorAll('button, a, div[class*="btn"]'));
    for (const el of btns) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (dlTexts.includes(t) && r.width > 0 && r.height > 0)
            return {type: 'button', text: t, tag: el.tagName};
    }
    // Priority 4: blob URL
    const vBlob = document.querySelector('video[src^="blob:"]');
    if (vBlob) return {type: 'blob', url: vBlob.src};
    return null;
}"""
    dl_found = None
    while time.time() < vid_wait_deadline:
        dl_found = page.evaluate(js_find_dl)
        if dl_found:
            _info(f"[dl] Found: {dl_found}")
            break
        _dismiss_all(page)
        time.sleep(3)
    
    # Now try to trigger the download
    # Note: MagicLight uses DIV elements for its download button (not <button> or <a>)
    # Use :text-is() (exact match) to avoid matching parent wrappers that
    # CONTAIN the text — those cause 3-minute expect_download timeouts on false
    # positive visible checks.
    download_selectors = [
        "button:text-is('Download video')",
        "a:text-is('Download video')",
        "div:text-is('Download video')",        # DIV-based button (seen in prod)
        "button:text-is('Download Video')",
        "a:text-is('Download Video')",
        "div:text-is('Download Video')",
        "button:text-is('Download')",
        "div[class*='btn']:text-is('Download')",
        "a[download]",
        "a[href*='.mp4']",
    ]

    def _try_download_click(loc):
        """Try click with expect_download; return (video_bytes, local_path) on success."""
        nonlocal video_dest
        try:
            with page.expect_download(timeout=30000) as dl_info:  # 30s per attempt
                loc.click()
            dl = dl_info.value
            if video_dest:
                dl.save_as(video_dest)
                if os.path.exists(video_dest) and os.path.getsize(video_dest) > 10000:
                    return None, video_dest
            else:
                try:
                    vb = dl.read()
                except Exception:
                    import tempfile
                    _tmp = tempfile.mktemp(suffix=".mp4")
                    dl.save_as(_tmp)
                    with open(_tmp, 'rb') as _f:
                        vb = _f.read()
                    try: os.remove(_tmp)
                    except: pass
                if len(vb) > 10000:
                    return vb, None
        except Exception as e:
            _dbg(f"    _try_download_click: {e}")
        return None, None

    for sel in download_selectors:
        if out["video"] or out.get("video_bytes"): break
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=2000):
                continue
            _info(f"[dl] Clicking '{sel}'...")
            vb, vp = _try_download_click(loc)
            if vp:
                out["video"] = vp
                _ok(f"Video -> {vp} ({os.path.getsize(vp)//1024} KB)")
            elif vb:
                out["video_bytes"] = vb
                _ok(f"Video downloaded ({len(vb)//1024} KB) - local save skipped")
        except Exception as e:
            _dbg(f"  dl-sel '{sel}': {e}")

    # JS-click fallback: handles any visible element with download-like text (covers DIV buttons)
    if not out["video"] and not out.get("video_bytes"):
        _info("[dl] Trying JS-click fallback for download button...")
        js_dl_click = """
() => {
    const texts = ['Download video', 'Download Video', 'Download'];
    const els = Array.from(document.querySelectorAll('button, a, div, span'));
    for (const el of els) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (texts.includes(t) && r.width > 0 && r.height > 0) {
            el.click();
            return el.tagName + ':' + t;
        }
    }
    return null;
}"""
        js_result = page.evaluate(js_dl_click)
        if js_result:
            _info(f"[dl] JS-click triggered: {js_result} — waiting for download...")
            try:
                with page.expect_download(timeout=60000) as dl_info:  # 60s for JS-click fallback
                    time.sleep(0.5)  # download may already be in flight
                dl = dl_info.value
                if video_dest:
                    dl.save_as(video_dest)
                    if os.path.exists(video_dest) and os.path.getsize(video_dest) > 10000:
                        out["video"] = video_dest
                        _ok(f"Video (JS-click) -> {video_dest} ({os.path.getsize(video_dest)//1024} KB)")
                else:
                    try:
                        vb = dl.read()
                    except Exception:
                        import tempfile
                        _tmp = tempfile.mktemp(suffix=".mp4")
                        dl.save_as(_tmp)
                        with open(_tmp, 'rb') as _f: vb = _f.read()
                        try: os.remove(_tmp)
                        except: pass
                    if len(vb) > 10000:
                        out["video_bytes"] = vb
                        _ok(f"Video (JS-click) downloaded ({len(vb)//1024} KB) - local save skipped")
            except Exception as e:
                _dbg(f"[dl] JS-click download wait failed: {e}")
        else:
            _info("[dl] No download button found via JS-click")
    if not out["video"]:
        vid_url = page.evaluate("""\
() => {
    const v = document.querySelector('video');
    if (v && v.src && v.src.includes('.mp4')) return v.src;
    const s = document.querySelector('video source');
    if (s && s.src && s.src.includes('.mp4')) return s.src;
    const a = document.querySelector('a[href*=".mp4"]');
    if (a) return a.href;
    return null;
}""")
        if vid_url:
            try:
                _info(f"[dl] Direct URL: {vid_url[:80]}")
                r = requests.get(vid_url, stream=True, timeout=180,
                                  cookies=cookies, headers=headers)
                r.raise_for_status()
                total = 0
                if video_dest:
                    with open(video_dest, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk:
                                f.write(chunk); total += len(chunk)
                    if total > 10000:
                        out["video"] = video_dest
                        _ok(f"Video (URL) -> {video_dest} ({total//1024} KB)")
                    else:
                        _warn(f"Video too small ({total}B)")
                        try: os.remove(video_dest)
                        except: pass
                else:
                    # Collect video bytes for direct Drive upload
                    video_bytes = b""
                    for chunk in r.iter_content(65536):
                        if chunk:
                            video_bytes += chunk; total += len(chunk)
                    if total > 10000:
                        out["video_bytes"] = video_bytes
                        _ok(f"Video (URL) downloaded ({total//1024} KB) - local save skipped")
                    else:
                        _warn(f"Video too small ({total}B)")
            except Exception as e:
                _warn(f"Video URL download error: {e}")
    if not out["video"] and not out.get("video_bytes"):
        _err("[dl] VIDEO DOWNLOAD FAILED")
    
    # Handle Drive upload for both file path and bytes
    if DRIVE_FOLDER_ID and (out.get("video") or out.get("video_bytes")):
        try:
            video_path = out.get("video")
            temp_video_path = None
            
            # If video is in bytes, save to temp file for upload
            if out.get("video_bytes") and not video_path:
                import tempfile
                temp_video_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                temp_video_path.write(out["video_bytes"])
                temp_video_path.close()
                video_path = temp_video_path.name
                _info(f"[drive] Saved video to temp file for upload: {video_path}")
            
            story_folder = os.path.dirname(video_path) if video_path else None
            drive_results = upload_story_to_drive(
                story_folder, safe_name,
                video_path, out.get("thumb", ""),
                sheet_row_num=sheet_row_num
            )
            out["drive_folder"] = drive_results["folder_link"]
            out["drive_link"]   = drive_results["video_link"]
            out["drive_thumb"]  = drive_results["thumb_link"]
            
            # Clean up temp file if used
            if temp_video_path and os.path.exists(temp_video_path.name):
                try:
                    os.remove(temp_video_path.name)
                    _info(f"[drive] Cleaned up temp file: {temp_video_path}")
                except Exception as cleanup_e:
                    _warn(f"[drive] Temp file cleanup error: {cleanup_e}")
                    
        except Exception as e:
            _warn(f"Drive upload error: {e}")
    return out

# ── RETRY via User Center ─────────────────────────────────────────────────────
def _retry_from_user_center(page, project_url, safe_name):
    _info("[retry] Opening User Center...")
    sleep_log(5, "pre-retry")
    try:
        page.goto("https://magiclight.ai/user-center/", timeout=60000)
        wait_site_loaded(page, None, timeout=45)
        sleep_log(4)
        _dismiss_all(page)
    except Exception as e:
        _warn(f"User Center failed: {e}"); return None
    clicked = page.evaluate("""\
(targetUrl) => {
    if (targetUrl) {
        const parts = targetUrl.replace(/[/]+$/, '').split('/');
        const projId = parts[parts.length - 1];
        if (projId && projId.length > 5) {
            const match = Array.from(document.querySelectorAll('a[href]'))
                .find(a => a.href && a.href.includes(projId));
            if (match && match.getBoundingClientRect().width > 0) {
                match.click(); return 'matched ID: ' + projId;
            }
        }
    }
    const editLinks = Array.from(document.querySelectorAll('a[href*="/project/edit/"],a[href*="/edit/"]'))
        .filter(a => a.getBoundingClientRect().width > 0);
    if (editLinks.length) { editLinks[0].click(); return 'edit-link'; }
    return null;
}""", project_url or "")
    if not clicked:
        if project_url and '/project/' in project_url:
            try:
                page.goto(project_url, timeout=60000)
                wait_site_loaded(page, None, timeout=30)
                sleep_log(3); _dismiss_all(page)
                _handle_generated_popup(page)
                sleep_log(2)
                return _download(page, safe_name)
            except Exception as e:
                _warn(f"Direct goto failed: {e}")
        _warn("[retry] Could not find project"); return None
    _ok(f"[retry] Project opened ({clicked})")
    sleep_log(5)
    wait_site_loaded(page, None, 30)
    _dismiss_all(page)
    _handle_generated_popup(page)
    sleep_log(2)
    try: return _download(page, safe_name)
    except Exception as e:
        _warn(f"[retry] Download failed: {e}"); return None

# ── Filename helpers ──────────────────────────────────────────────────────────
def _make_safe(row_num, title, file_type=""):
    safe_title = re.sub(r"[^\w\-]", "_", str(title)[:30])
    if file_type:
        return f"R{row_num}_{safe_title}_{file_type}".strip("_")
    return re.sub(r"[^\w\-]", "_", f"R{row_num}_{safe_title}").strip("_")

def extract_row_num(stem: str) -> int | None:
    m = re.match(r"R(\d+)_", stem)
    if m:
        return int(m.group(1))
    # Fallback to old pattern for backward compatibility
    m = re.match(r"row(\d+)[_\-]", stem, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

# ── Video Processing ──────────────────────────────────────────────────────────
def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def has_valid_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=10
        )
        return float(result.stdout.strip()) > 0
    except Exception:
        return False

def has_audio_stream(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False

def scan_videos(base: Path) -> list[Path]:
    if not base or not base.exists():
        return []
    return sorted(
        p for p in base.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.endswith("_processed")
        and "-Processed-" not in p.stem
        and "_thumb" not in p.stem
    )

_PROFILES = {
    "720p": {
        "label": "720p — Fast Encode",
        "resolution": "1280x720", "crf": 23,
        "preset": "fast", "audio_br": "128k",
    },
    "1080p": {
        "label": "1080p — Standard",
        "resolution": "1920x1080", "crf": 23,
        "preset": "veryfast", "audio_br": "128k",
    },
    "1080p_hq": {
        "label": "1080p HQ — Best Quality (Slow)",
        "resolution": "1920x1080", "crf": 18,
        "preset": "slow", "audio_br": "192k",
    },
}

def build_ffmpeg_cmd(
    input_file: Path, output_file: Path,
    trim_seconds: int, logo_path: Path,
    logo_x: int, logo_y: int, logo_width: int, logo_opacity: float,
    endscreen_enabled: bool, endscreen_path, profile_key: str = "1080p"
) -> list[str]:
    # Validate inputs before processing
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    if not has_valid_video(input_file):
        raise ValueError(f"Invalid video file: {input_file}")
    if trim_seconds < 0:
        raise ValueError(f"trim_seconds must be non-negative, got {trim_seconds}")
    
    profile = _PROFILES.get(profile_key, _PROFILES["1080p"])
    res = profile["resolution"]
    w, h = res.split("x")
    scale = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    crf     = profile["crf"]
    preset  = profile["preset"]
    ab      = profile["audio_br"]
    
    dur = get_duration(input_file)
    if dur <= 0:
        raise ValueError(f"Cannot determine video duration for: {input_file}")
    
    # Fixed trim duration calculation - prevent negative/zero duration
    if trim_seconds >= dur:
        _warn(f"trim_seconds ({trim_seconds}) >= video duration ({dur:.1f}), using full video")
        trim_dur = dur
    else:
        trim_dur = dur - trim_seconds
    
    if trim_dur <= 0.1:
        raise ValueError(f"Resulting video duration too short: {trim_dur:.1f}s")
    
    input_has_audio = has_audio_stream(input_file)
    has_logo      = logo_path.exists() and logo_width > 0
    has_endscreen = (endscreen_enabled and endscreen_path and
                     Path(endscreen_path).exists() and has_valid_video(Path(endscreen_path)))
    
    inputs = ["-i", str(input_file)]
    logo_idx = end_idx = None
    if has_logo:
        logo_idx = len(inputs) // 2
        inputs += ["-i", str(logo_path)]
    if has_endscreen:
        end_idx = len(inputs) // 2
        inputs += ["-i", str(endscreen_path)]
    
    filters = []
    filters.append(f"[0:v]trim=duration={trim_dur:.3f},setpts=PTS-STARTPTS,{scale}[base]")
    if input_has_audio:
        filters.append(f"[0:a]atrim=duration={trim_dur:.3f},asetpts=PTS-STARTPTS[main_a]")
    
    if has_logo:
        logo_scale = f"[{logo_idx}:v]scale={logo_width}:-1[logo_s]"
        if logo_opacity < 1.0:
            logo_scale += f";[logo_s]format=rgba,colorchannelmixer=aa={logo_opacity:.2f}[logo_f]"
            lref = "logo_f"
        else:
            lref = "logo_s"
        filters.append(logo_scale)
        filters.append(f"[base][{lref}]overlay={logo_x}:{logo_y}[vid_logo]")
        main_v = "vid_logo"
    else:
        main_v = "base"
    
    if has_endscreen:
        end_dur = get_duration(Path(endscreen_path))
        if end_dur <= 0:
            raise ValueError(f"Invalid endscreen duration: {end_dur}")
        
        # Fixed crossfade calculation - ensure minimum valid duration
        cross = min(0.5, trim_dur * 0.04, end_dur * 0.3, trim_dur * 0.25)  # Max 25% of main video
        cross = max(0.1, cross)  # Minimum 0.1s crossfade
        
        if cross >= trim_dur:
            _warn(f"Crossfade duration ({cross:.1f}s) too long for video ({trim_dur:.1f}s), disabling endscreen")
            has_endscreen = False
        else:
            xfade_off = max(0, trim_dur - cross)
            filters.append(f"[{end_idx}:v]trim=duration={end_dur:.3f},setpts=PTS-STARTPTS,{scale}[end_v]")
            if input_has_audio:
                filters.append(f"[{end_idx}:a]atrim=duration={end_dur:.3f},asetpts=PTS-STARTPTS[end_a]")
                filters.append(f"[{main_v}][end_v]xfade=transition=fade:duration={cross:.3f}:offset={xfade_off:.3f}[final_v]")
                filters.append(f"[main_a][end_a]acrossfade=d={cross:.3f}[final_a]")
                map_v, map_a = "[final_v]", "[final_a]"
            else:
                filters.append(f"[{main_v}][end_v]xfade=transition=fade:duration={cross:.3f}:offset={xfade_off:.3f}[final_v]")
                map_v, map_a = "[final_v]", None
    
    if not has_endscreen:
        map_v = f"[{main_v}]"
        map_a = "[main_a]" if input_has_audio else None
    
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters),
            "-map", map_v])
    if map_a:
        cmd += ["-map", map_a, "-c:a", "aac", "-b:a", ab]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_file)]
    return cmd

def run_ffmpeg(cmd: list[str], input_file: Path, output_file: Path,
               dry_run: bool = False) -> bool:
    if dry_run:
        _info(f"[DRY-RUN] {' '.join(cmd[:6])} ...")
        return True
    
    duration = get_duration(input_file)
    proc = None
    stdout_lines = []
    
    try:
        # Fixed: Use context manager for proper resource cleanup
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, universal_newlines=True,
                              bufsize=1) as proc:
            
            if _has_rich:
                from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                              BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                              TimeElapsedColumn(), console=console) as progress:
                    task = progress.add_task(f"[cyan]Encoding {input_file.name}", total=100)
                    for line in proc.stdout:
                        stdout_lines.append(line.strip())
                        if "time=" in line:
                            try:
                                tp = line.split("time=")[1].split()[0]
                                h, m, s = tp.split(":")
                                cur = int(h) * 3600 + int(m) * 60 + float(s)
                                if duration > 0:
                                    progress.update(task, completed=min(100, int(cur/duration*100)))
                            except: pass
            else:
                for line in proc.stdout:
                    stdout_lines.append(line.strip())
                    if "time=" in line: console.print(f"  {line.strip()}")
            
            rc = proc.wait()
            
        if rc == 0:
            _ok(f"Encoded -> {output_file.name}")
            return True
        else:
            # Fixed: Log stderr output for debugging
            _err(f"FFmpeg exited with code {rc}")
            if stdout_lines:
                _warn("Last 5 lines of FFmpeg output:")
                for line in stdout_lines[-5:]:
                    _info(f"  {line}")
            return False
            
    except subprocess.TimeoutExpired:
        _err(f"FFmpeg timeout for {input_file.name}")
        if proc:
            proc.kill()
            proc.wait()
        return False
    except Exception as e:
        _err(f"FFmpeg error: {e}")
        if proc:
            try:
                proc.kill()
                proc.wait()
            except:
                pass
        return False

def process_video(input_video: Path, dry_run: bool = False) -> bool:
    if not LOCAL_OUTPUT_ENABLED:
        _warn("[process] Local output disabled — skipping video processing")
        return False
    
    if not check_ffmpeg():
        _err("FFmpeg not found. Install FFmpeg and add to PATH.")
        return False
    
    # Fixed: Add comprehensive input validation
    if not input_video.exists():
        _err(f"Input video not found: {input_video}")
        return False
    
    if not has_valid_video(input_video):
        _err(f"Invalid video file: {input_video}")
        return False
    
    file_size_mb = input_video.stat().st_size / (1024 * 1024)
    if file_size_mb < 0.1:  # Less than 100KB
        _warn(f"Video file too small ({file_size_mb:.1f}MB): {input_video}")
        return False
    
    stem = input_video.stem
    row_num = extract_row_num(stem)
    
    # Extract title part with better error handling
    if "-Generated-" in stem:
        title_part = stem.split("-Generated-", 1)[1]
    elif "_" in stem:
        parts = stem.split("_", 1)
        title_part = parts[1] if len(parts) > 1 else stem
    else:
        title_part = stem
    
    # Generate output filename
    if row_num:
        safe_name   = _make_safe(row_num, title_part.replace("_", " "), "Processed")
        output_file = input_video.parent / f"{safe_name}{input_video.suffix}"
    else:
        output_file = input_video.parent / f"{input_video.stem}_processed{input_video.suffix}"
    
    if output_file.exists():
        _info(f"Already processed — skipping ({output_file.name})")
        return True
    
    # Validate assets before processing
    endscreen_enabled = ENDSCREEN_ENABLED
    endscreen_path    = ENDSCREEN_VIDEO
    if ENDSCREEN_ENABLED:
        if not ENDSCREEN_VIDEO.exists():
            _warn(f"Endscreen not found — skipping endscreen")
            endscreen_enabled = False
            endscreen_path    = None
        elif not has_valid_video(ENDSCREEN_VIDEO):
            _warn(f"Endscreen video invalid — skipping endscreen")
            endscreen_enabled = False
            endscreen_path    = None
    
    if not LOGO_PATH.exists():
        _warn(f"Logo not found: {LOGO_PATH}")
    
    try:
        cmd = build_ffmpeg_cmd(
            input_file=input_video, output_file=output_file,
            trim_seconds=TRIM_SECONDS, logo_path=LOGO_PATH,
            logo_x=LOGO_X, logo_y=LOGO_Y, logo_width=LOGO_WIDTH,
            logo_opacity=LOGO_OPACITY, endscreen_enabled=endscreen_enabled,
            endscreen_path=endscreen_path
        )
        _info(f"Processing -> {output_file.name}")
        success = run_ffmpeg(cmd, input_video, output_file, dry_run=dry_run)
        
        # Fixed: Validate output file after processing
        if success and not dry_run:
            if not output_file.exists():
                _err(f"Output file not created: {output_file}")
                return False
            if not has_valid_video(output_file):
                _err(f"Output file invalid: {output_file}")
                try:
                    output_file.unlink()  # Remove corrupt file
                except:
                    pass
                return False
            
            output_size_mb = output_file.stat().st_size / (1024 * 1024)
            _ok(f"Processing complete: {output_size_mb:.1f}MB")
        
        return success
        
    except Exception as e:
        _err(f"Processing failed: {e}")
        # Clean up partial output file on failure
        if output_file.exists():
            try:
                output_file.unlink()
                _info(f"Cleaned up partial file: {output_file}")
            except:
                pass
        return False

def process_all(cfg: dict, videos: list[Path] = None,
                dry_run: bool = False, upload: bool = False,
                upload_youtube: bool = False) -> int:
    base = cfg.get("magiclight_output", Path(OUT_BASE))
    if videos is None:
        videos = scan_videos(base)
    if not videos:
        _warn("No unprocessed videos found.")
        return 0
    ok = fail = 0
    total = len(videos)
    for i, vid in enumerate(videos, 1):
        console.rule(f"[cyan][{i}/{total}]  {vid.parent.name} / {vid.name}[/cyan]")
        row_num = extract_row_num(vid.stem)
        if "-Generated-" in vid.stem:
            title_part = vid.stem.split("-Generated-", 1)[1]
        elif "_" in vid.stem:
            title_part = vid.stem.split("_", 1)[1]
        else:
            title_part = vid.stem
        if row_num:
            safe_name  = _make_safe(row_num, title_part.replace("_", " "), "Processed")
            dst        = vid.parent / f"{safe_name}{vid.suffix}"
        else:
            dst = vid.parent / f"{vid.stem}_processed{vid.suffix}"
        if dst.exists():
            _info(f"Already processed — skipping ({dst.name})")
            ok += 1
            continue
        dur = get_duration(vid)
        mb  = vid.stat().st_size / 1_048_576
        _info(f"Duration : {dur:.1f}s   Size: {mb:.1f} MB")
        _info(f"Output   : {dst.name}")
        success = process_video(vid, dry_run=dry_run)
        if success:
            ok += 1
            if upload and not dry_run and dst.exists():
                folder_name       = vid.parent.name if vid.parent.name else vid.stem
                processed_link    = upload_to_drive(str(dst), folder_name)
                # ── YouTube Upload (optional — only if --upload-youtube flag diya) ──
                if upload_youtube:
                    _step("[youtube] Starting YouTube upload...")
                    upload_story_to_youtube(
                        story_title    = title_part.replace("_", " "),
                        gen_summary    = "",
                        gen_tags       = "",
                        video_path     = str(dst),
                        thumbnail_path = "",
                        sheet_row_num  = row_num
                    )
                if row_num and processed_link:
                    try:
                        update_sheet_row(
                            row_num,
                            Status         = "Done",
                            Process_D_Link = processed_link,
                            Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            Notes          = f"Processed OK"
                        )
                        _ok(f"[sheet] Row {row_num} -> Done | Process_D_Link written")
                    except Exception as se:
                        _warn(f"[sheet] Process_D_Link update: {se}")
                elif row_num and not processed_link:
                    try:
                        update_sheet_row(
                            row_num,
                            Status         = "Done",
                            Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            Notes          = "Processed OK (Drive upload failed)"
                        )
                    except Exception as se:
                        _warn(f"[sheet] Status update: {se}")
        else:
            fail += 1
            if dst.exists() and not dry_run:
                try: dst.unlink()
                except: pass
    console.print()
    console.rule()
    _ok(f"Processing complete!  OK={ok}  FAIL={fail}")
    return 0 if fail == 0 else 1

# ── Config helpers ────────────────────────────────────────────────────────────
def load_process_cfg():
    return {
        "magiclight_output": Path(OUT_BASE),
        "logo_path":         LOGO_PATH,
        "endscreen_video":   ENDSCREEN_VIDEO,
        "trim_seconds":      TRIM_SECONDS,
        "logo_x": LOGO_X, "logo_y": LOGO_Y,
        "logo_width": LOGO_WIDTH, "logo_opacity": LOGO_OPACITY,
        "endscreen_enabled": ENDSCREEN_ENABLED,
        "upload_to_drive":   UPLOAD_TO_DRIVE,
        "drive_folder_id":   DRIVE_FOLDER_ID,
        "spreadsheet_id":    SHEET_ID,
    }

def run_health_check():
    console.rule("[bold cyan]System Health Check[/bold cyan]")
    issues = 0
    py = sys.version_info
    if py.major >= 3 and py.minor >= 8:
        _ok(f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        _err(f"Python too old: {py.major}.{py.minor}"); issues += 1
    packages = {
        'playwright': 'playwright', 'gspread': 'gspread',
        'google-auth-oauthlib': 'google_auth_oauthlib',
        'google-api-python-client': 'googleapiclient', 'python-dotenv': 'dotenv'
    }
    for pkg, imp in packages.items():
        try:
            __import__(imp); _ok(f"Package: {pkg}")
        except ImportError:
            _err(f"Missing: {pkg}"); issues += 1
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0: _ok("FFmpeg installed")
        else: _err("FFmpeg error"); issues += 1
    except FileNotFoundError:
        _err("FFmpeg not found in PATH!"); issues += 1

    # Assets check
    if LOGO_PATH.exists():
        _ok(f"Logo found: {LOGO_PATH}")
    else:
        _warn(f"Logo missing: {LOGO_PATH}")
    if ENDSCREEN_VIDEO.exists():
        _ok(f"Endscreen found: {ENDSCREEN_VIDEO}")
    else:
        _warn(f"Endscreen missing: {ENDSCREEN_VIDEO} (optional)")

    # .env check
    for var in ["SHEET_ID", "DRIVE_FOLDER_ID"]:
        val = os.getenv(var, "")
        if val:
            _ok(f"{var} set")
        else:
            _warn(f"{var} not set in .env")

    console.print()
    if issues == 0:
        _ok("All core systems OK!")
    else:
        _err(f"Found {issues} issue(s)")
    return issues

# ── Menu State ────────────────────────────────────────────────────────────────
MENU_STATE_FILE = ".menu_state.json"

def load_menu_state():
    try:
        if os.path.exists(MENU_STATE_FILE):
            with open(MENU_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return {"last_mode": None, "last_amount": 0, "last_drive_choice": True, "preferences": {}}

def save_menu_state(state):
    try:
        with open(MENU_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)
    except: pass

def show_pending_table():
    """Show pending stories in a styled Rich table."""
    try:
        records = read_sheet()
    except Exception as e:
        _warn(f"Could not read sheet: {e}")
        return 0

    pending   = [(i+2, r) for i, r in enumerate(records) if str(r.get("Status","")).strip().lower() == "pending"]
    done      = sum(1 for r in records if str(r.get("Status","")).strip().lower() == "done")
    errors    = sum(1 for r in records if str(r.get("Status","")).strip().lower() in ("error","no_video"))
    total     = len(records)

    # Stats row
    stats = Table.grid(padding=(0, 3))
    stats.add_column(); stats.add_column(); stats.add_column(); stats.add_column()
    stats.add_row(
        f"[bold]Total[/bold]  [cyan]{total}[/cyan]",
        f"[bold]Pending[/bold]  [yellow]{len(pending)}[/yellow]",
        f"[bold]Done[/bold]  [green]{done}[/green]",
        f"[bold]Errors[/bold]  [red]{errors}[/red]",
    )
    console.print(stats)
    console.print()

    if not pending:
        console.print("  [dim]No pending stories.[/dim]")
        return 0

    t = Table(
        show_header=True, header_style="bold cyan",
        border_style="dim", show_lines=False,
        title=f"[bold]Pending Stories ({len(pending)})[/bold]",
        title_style="cyan",
        min_width=70,
    )
    t.add_column("#",     style="dim",    width=4,  justify="right")
    t.add_column("Row",   style="cyan",   width=5,  justify="center")
    t.add_column("Theme", style="yellow", width=16)
    t.add_column("Title", style="white",  width=40)

    for idx, (row_num, row) in enumerate(pending[:15], 1):
        title = str(row.get("Title", "")).strip()[:38] or "(no title)"
        theme = str(row.get("Theme", "")).strip()[:14] or "—"
        t.add_row(str(idx), f"R{row_num}", theme, title)

    if len(pending) > 15:
        t.add_row("...", "", "", f"[dim]...and {len(pending)-15} more[/dim]")

    console.print(t)
    return len(pending)

def ask_amount(mode_label: str) -> int:
    state   = load_menu_state()
    default = state.get("last_amount", 1)
    ans = console.input(
        f"\n  [bold cyan]🔄[/bold cyan] How many stories for [bold]{mode_label}[/bold]?"
        f" [dim](0=all, last={default})[/dim] : "
    ).strip()
    amount = int(ans) if ans.isdigit() else (default if ans == "" else 0)
    state["last_amount"] = amount
    save_menu_state(state)
    return amount

def ask_drive() -> bool:
    state   = load_menu_state()
    default = state.get("last_drive_choice", True)
    dstr    = "Y" if default else "N"
    ans = console.input(
        f"  [bold cyan]🔄[/bold cyan] Upload to Google Drive?"
        f" [dim](Y/N, last={dstr})[/dim] : "
    ).strip().upper()
    choice = (ans == "Y") if ans in ("Y","N") else default
    state["last_drive_choice"] = choice
    save_menu_state(state)
    return choice

# ── FIX v2.0.3: _run_pipeline_core ───────────────────────────────────────────
def _run_pipeline_core(limit, source_type="auto"):
    global _browser, DRIVE_FOLDER_ID, _credits_total, _credits_used, _cws, _gc, _ws, _hdr
    try:
        records = read_sheet()
    except Exception as e:
        _err(f"Could not read sheet: {e}"); return
    pending = [(i, r) for i, r in enumerate(records)
               if str(r.get("Status", "")).strip().lower() == "pending"]
    if not pending:
        _warn("No pending stories found."); return
    if limit > 0:
        pending = pending[:limit]
    accounts = []
    if os.path.exists("accounts.txt"):
        with open("accounts.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    u, p = line.split(":", 1)
                    accounts.append((u.strip(), p.strip()))
    if not accounts:
        if EMAIL and PASSWORD: accounts = [(EMAIL, PASSWORD)]
        else: _err("No credentials in accounts.txt or .env"); return
    
    import random
    random.shuffle(accounts)
    account_idx = 0
    _credits_total = 0
    _credits_used  = 0
    _ok(f"Processing {len(pending)} stor{'y' if len(pending)==1 else 'ies'}")
    _ok(f"Accounts loaded: {len(accounts)}")
    curr_email, curr_pw = accounts[account_idx]
    os.environ["CURRENT_EMAIL"] = curr_email
    context = _browser.new_context(accept_downloads=True, no_viewport=True)
    page    = context.new_page()
    try:
        login(page, custom_email=curr_email, custom_pw=curr_pw)
    except Exception as e:
        _err(f"[FATAL] Login failed for {curr_email}: {e}")
        return
    for rec_idx, row in pending:
        if _shutdown: break
        credit_before = 0
        try:
            page.goto("https://magiclight.ai/user-center", timeout=30000)
            page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                    state="visible", timeout=10000)
            credit_before, _ = _read_credits_from_page(page)
        except Exception as ce:
            _dbg(f"[credits] credit_before read failed: {ce}")
            credit_before = max(0, _credits_total - _credits_used)
        # Fixed: Add atomic account rotation with proper cleanup
        if credit_before == 0 or (credit_before > 0 and credit_before < 70):
            _warn(f"[Rotate] Account {curr_email} exhausted (credits: {credit_before})")
            
            # Clean up current context before switching
            try:
                if 'context' in locals() and context:
                    if not context.is_closed():
                        context.close()
            except Exception as cleanup_e:
                _dbg(f"[rotate] Context cleanup error: {cleanup_e}")
            
            account_idx += 1
            if account_idx >= len(accounts):
                _err("All accounts exhausted — stopping."); break
            
            _credits_total = 0; _credits_used = 0
            curr_email, curr_pw = accounts[account_idx]
            os.environ["CURRENT_EMAIL"] = curr_email
            
            _step(f"[Rotate] Switching to {curr_email}")
            
            # Create new context and login with retry
            rotation_success = False
            for rotation_attempt in range(2):
                try:
                    context = _browser.new_context(accept_downloads=True, no_viewport=True)
                    page = context.new_page()
                    
                    login(page, custom_email=curr_email, custom_pw=curr_pw)
                    
                    # Verify new account has credits
                    credit_before, _ = _read_credits_from_page(page)
                    if credit_before >= 70:
                        _ok(f"[Rotate] Successfully switched to {curr_email} (credits: {credit_before})")
                        rotation_success = True
                        break
                    else:
                        _warn(f"[Rotate] New account also low on credits: {credit_before}")
                        if not context.is_closed():
                            context.close()
                        
                except Exception as re_err:
                    _warn(f"[Rotate] Rotation attempt {rotation_attempt + 1} failed: {re_err}")
                    try:
                        if 'context' in locals() and context and not context.is_closed():
                            context.close()
                    except:
                        pass
                    sleep_log(3, f"rotation retry {rotation_attempt + 1}")
            
            if not rotation_success:
                _err(f"[Rotate] Failed to switch to account {curr_email}")
                break
        vals = list(row.values())
        col_c = str(vals[2]).strip() if len(vals) > 2 else ""
        col_d = str(vals[3]).strip() if len(vals) > 3 else ""
        col_e = str(vals[4]).strip() if len(vals) > 4 else ""
        story = f"{col_c}\n\n{col_d}\n\n{col_e}".strip()
        if not story:
            _warn(f"Row {rec_idx+2}: empty Story — skipping"); continue
        title   = str(row.get("Title", f"Row{rec_idx+2}")).strip() or f"Row{rec_idx+2}"
        row_num = rec_idx + 2
        safe    = _make_safe(row_num, title, "Generated")
        console.print(Rule(style="cyan"))
        console.print(Panel(
            f"[bold]Row {row_num}[/bold]  {title}\n"
            f"[dim]Account: {curr_email}   Credit: {credit_before}[/dim]",
            border_style="cyan", expand=False, padding=(0, 1)
        ))
        try:
            update_sheet_row(row_num,
                Status       = "Processing",
                Email_Used   = curr_email,
                Credit_Before= str(credit_before) if credit_before else "",
                Created_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as se:
            _warn(f"[sheet] Initial write failed: {se}")
        project_url = ""
        result      = None
        credit_after = 0
        try:
            step1(page, story)
            if _credit_exhausted(page):
                _err("[Low Credit] Stopping")
                update_sheet_row(row_num, Status="Low Credit",
                                  Notes="Credits exhausted before Step 2",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
            step2(page)
            step3(page)
            project_url = page.url
            _credits_used += 60
            result = step4(page, safe, sheet_row_num=row_num)
            try:
                page.goto("https://magiclight.ai/user-center", timeout=40000)
                page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                        state="visible", timeout=20000)
                time.sleep(3)
                credit_after, _ = _read_credits_from_page(page)
                _credits_total = credit_after
                page.goto("https://magiclight.ai/kids-story/", timeout=30000)
            except Exception as ca_err:
                _dbg(f"[credits] credit_after read failed: {ca_err}")
                credit_after = max(0, credit_before - 60)
            _update_credits_completion(curr_email, credit_before, credit_before - credit_after,
                                       row_num, "Generation", "Step4+")
            if _credit_exhausted(page):
                update_sheet_row(row_num, Status="Low Credit",
                                  Credit_After=str(credit_after),
                                  Notes="Credits exhausted post-render",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
        except Exception as e:
            screenshot(page, f"error_row{row_num}")
            debug_buttons(page)
            _err(f"Row {row_num} error: {e}")
            if _credit_exhausted(page):
                update_sheet_row(row_num, Status="Low Credit",
                                  Notes="Credits exhausted during generation",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
            try: result = _retry_from_user_center(page, project_url, safe)
            except Exception as re_err:
                _warn(f"[retry] {re_err}"); result = None
            if not result:
                update_sheet_row(row_num, Status="Error",
                                  Notes=str(e)[:150],
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                _err(f"Row {row_num} -> Error")
                sleep_log(5); continue
        # Success = local video file saved OR drive upload succeeded OR bytes in memory
        video_ok = bool(
            result and (
                result.get("video") or           # local file saved
                result.get("drive_link") or      # uploaded to Drive (bytes path)
                result.get("video_bytes")        # bytes in memory (pre-upload)
            )
        )
        if video_ok:

            try:
                update_sheet_row(row_num,
                    Status        = "Generated",
                    Gen_Title     = result.get("gen_title", ""),
                    Gen_Summary   = result.get("summary", "")[:200],
                    Gen_Tags      = result.get("tags", ""),
                    Drive_Link    = result.get("drive_link", ""),
                    DriveImg_Link = result.get("drive_thumb", ""),
                    Project_URL   = project_url,
                    Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    Email_Used    = curr_email,
                    Credit_Before = str(credit_before),
                    Credit_After  = str(credit_after),
                    Notes         = f"Generated OK | Credit: {credit_before}->{credit_after}"
                )
                _ok(f"[sheet] Row {row_num} -> Generated  Credit: {credit_before}->{credit_after}")
            except Exception as se:
                _warn(f"[sheet] Generated write failed: {se}")
        else:
            try:
                update_sheet_row(row_num,
                    Status        = "No_Video",
                    Email_Used    = curr_email,
                    Credit_Before = str(credit_before),
                    Credit_After  = str(credit_after),
                    Notes         = "Video generation failed",
                    Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            except Exception as se:
                _warn(f"[sheet] No_Video write failed: {se}")
            _warn(f"Row {row_num} -> No_Video")
            continue
        # Inline processing: only in combined mode, not generate-only
        mode_env = os.environ.get("PIPELINE_MODE", "generate")
        if os.environ.get("RUN_PROCESS_INLINE") == "1" and mode_env == "combined":
            _info("[pipeline] Starting inline video processing...")
            video_path = result.get("video", "")
            if video_path and os.path.exists(video_path):
                try:
                    vid_path = Path(video_path)
                    success  = process_video(vid_path, dry_run=False)
                    if success:
                        row_n    = extract_row_num(vid_path.stem)
                        if "-Generated-" in vid_path.stem:
                            title_p = vid_path.stem.split("-Generated-", 1)[1]
                        else:
                            title_p = vid_path.stem.split("_", 1)[1] if "_" in vid_path.stem else vid_path.stem
                        if row_n:
                            proc_name = _make_safe(row_n, title_p.replace("_", " "), "Processed")
                            proc_path = vid_path.parent / f"{proc_name}{vid_path.suffix}"
                        else:
                            proc_path = vid_path.parent / f"{vid_path.stem}_processed{vid_path.suffix}"
                        if proc_path.exists():
                            _ok(f"[pipeline] Processed: {proc_path.name}")
                            processed_link = ""
                            if getattr(args, 'upload_drive', False) or UPLOAD_TO_DRIVE:
                                folder_name    = os.path.basename(os.path.dirname(str(proc_path)))
                                processed_link = upload_to_drive(str(proc_path), folder_name)
                            try:
                                # Write Process_D_Link if column exists, else overwrite Drive_Link
                                actual = _actual_sheet_cols()
                                if "Process_D_Link" in actual:
                                    update_sheet_row(row_num,
                                        Status         = "Done",
                                        Process_D_Link = processed_link,
                                        Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        Notes          = f"Done | Account: {curr_email}"
                                    )
                                else:
                                    # No Process_D_Link column — update Drive_Link with processed video
                                    update_sheet_row(row_num,
                                        Status         = "Done",
                                        Drive_Link     = processed_link if processed_link else result.get("drive_link", ""),
                                        Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        Notes          = f"Done | Account: {curr_email}"
                                    )
                                _ok(f"[sheet] Row {row_num} -> Done")
                                # ── YouTube Upload (--upload-youtube flag ho to) ──
                                if getattr(args, 'upload_youtube', False):
                                    _step("[youtube] Starting YouTube upload...")
                                    upload_story_to_youtube(
                                        story_title    = title,
                                        gen_summary    = row.get("Gen_Summary", ""),
                                        gen_tags       = row.get("Gen_Tags", ""),
                                        video_path     = str(proc_path),
                                        thumbnail_path = None,
                                        sheet_row_num  = row_num
                                    )
                            except Exception as se:
                                _warn(f"[sheet] Done write failed: {se}")
                        else:
                            _warn("Processed file not found after processing")
                            update_sheet_row(row_num, Status="Error",
                                              Notes="Processed file missing after encoding")
                    else:
                        _warn("Video processing failed")
                        update_sheet_row(row_num, Status="Error",
                                          Notes="Video processing (FFmpeg) failed",
                                          Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except Exception as pe:
                    _warn(f"Processing error: {pe}")
                    update_sheet_row(row_num, Status="Error",
                                      Notes=f"Processing error: {str(pe)[:150]}",
                                      Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            else:
                _warn("Video file not available for processing")
                update_sheet_row(row_num, Status="Generated",
                                  Notes="Generated OK but local file missing for processing")
        else:
            _ok(f"[sheet] Row {row_num} -> Generated (generate-only mode)")
        if len(pending) > 1:
            sleep_log(5, "cooldown")
    try:
        context.close()
    except: pass
    console.rule(style="cyan")
    _ok("Generation sequence complete.")

# ── MENU ──────────────────────────────────────────────────────────────────────
def menu():
    state     = load_menu_state()
    
    console.print()
    console.print(Panel(
        f"[bold cyan]MagicLight Auto[/bold cyan]   [dim]v{__version__}[/dim]\n"
        f"[dim]Automated Kids Story Video Generation[/dim]",
        border_style="cyan", padding=(0, 2), expand=False
    ))
    console.print()

    show_pending_table()
    console.print()

    mt = Table(show_header=False, box=None, padding=(0, 2))
    mt.add_column("num",  style="bold cyan", justify="right", width=5)
    mt.add_column("name", style="bold white", width=50)
    mt.add_row("[1]", "🚀 Full Pipeline (Generate -> Process -> Upload)")
    mt.add_row("[2]", "🎥 Generate Mode (Video Story Making Only)")
    mt.add_row("[3]", "🎬 Process Mode (Encode & Upload Videos)")
    mt.add_row("[4]", "💰 Check Account Credits (Log all accounts)")
    mt.add_row("[5]", "❌ Exit")
    console.print(mt)
    console.print()

    choice = console.input("  [bold cyan]Select Pipeline or Option [1-5]: [/bold cyan]").strip()
    
    # Handle option 4 - Check Account Credits
    if choice == "4":
        check_all_accounts_credits()
        return
    
    if choice not in ["1", "2", "3"]: return

    mode_map = {"1": "combined", "2": "generate", "3": "process"}
    mode = mode_map[choice]

    amount = ask_amount("Stories")
    upload_drive = ask_drive()
    args.upload_drive = upload_drive
    
    loop_mode = False
    if mode in ["combined", "generate"]:
        loop_choice = console.input(f"  [bold cyan]🔄 Run on loop (Y/N)? [/bold cyan]").strip().upper()
        loop_mode = (loop_choice == "Y")
        if loop_mode:
            _ok("[loop] Loop mode enabled")
            if not DRIVE_FOLDER_ID:
                _err("DRIVE_FOLDER_ID required for Loop mode!"); return

    console.print()
    cfg = load_process_cfg()

    if mode in ["combined", "generate"]:
        pw_manager = sync_playwright().start()
        global _browser
        _browser = pw_manager.chromium.launch(
            headless=getattr(args, "headless", True),
            args=["--start-maximized"]
        )
        try:
            while True:
                os.environ["PIPELINE_MODE"]      = mode
                os.environ["RUN_PROCESS_INLINE"] = "1" if mode == "combined" else "0"
                _credits_used = 0
                _run_pipeline_core(limit=amount, source_type="auto")
                
                if not loop_mode:
                    break
                else:
                    sleep_log(30, "Loop cooldown...")
        finally:
            try:
                if _browser: _browser.close()
            except: pass
            try: pw_manager.stop()
            except: pass
    elif mode == "process":
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        process_all(cfg, videos=vids, upload=args.upload_drive)

# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    """Enhanced argument parser with beautiful help output"""
    parser = argparse.ArgumentParser(
        description="""
🎬 MagicLight Auto v{version} - Kids Story Video Pipeline

✨ Features:
  • Automated story generation via MagicLight.ai
  • Video processing with FFmpeg
  • Google Drive upload integration
  • Google Sheets tracking
  • Multi-account support

🎯 Modes:
  • combined  - Full pipeline (generate → process → upload)
  • generate  - Story generation only
  • process   - Video processing only
  • loop      - Continuous processing
        """.format(version=__version__),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Mode options
    parser.add_argument(
        "--mode", 
        choices=["combined", "generate", "process", "loop"],
        help="🔧 Pipeline mode to run"
    )
    
    # Processing options
    parser.add_argument(
        "--max", 
        type=int, 
        default=0,
        help="📊 Maximum stories to process (0 = all pending)"
    )
    
    parser.add_argument(
        "--headless", 
        action="store_true",
        help="🤖 Run browser without UI"
    )
    
    parser.add_argument(
        "--upload-drive", 
        action="store_true",
        help="☁️ Upload videos to Google Drive"
    )
    
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="👁️ Preview only, no actual processing"
    )
    
    parser.add_argument(
        "--loop", 
        action="store_true",
        help="🔄 Infinite loop mode (1 story per cycle)"
    )
    
    # Debug and utility options
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="🐛 Enable verbose debug logging"
    )
    
    parser.add_argument(
        "--migrate-schema", 
        action="store_true",
        help="📋 Initialize Google Sheet with correct headers"
    )
    
    parser.add_argument(
        "--check-credits", 
        action="store_true", 
        help="💰 Check all accounts and log credits to Credits sheet"
    )


    parser.add_argument(
        "--upload-youtube",
        action="store_true",
        help="📺 Upload processed videos to YouTube"
    )
 
    return parser.parse_args()

def run_cli_mode(args):
    global _browser, _credits_used, DEBUG
    if getattr(args, 'debug', False):
        DEBUG = True
        os.environ["DEBUG"] = "1"
    
    # Handle --check-credits flag
    if getattr(args, 'check_credits', False):
        check_all_accounts_credits(headless=getattr(args, 'headless', False))
        return True
    
    if getattr(args, 'mode', None) == 'loop':
        args.mode = 'combined'
        args.loop = True
    # If no mode specified but other CLI flags are present, default to generate mode
    if not args.mode and (getattr(args, 'max', 0) > 0 or getattr(args, 'headless', False) or getattr(args, 'upload_drive', False)):
        args.mode = 'generate'
    if not args.mode:
        return False
    mode      = args.mode.lower()
    amount    = args.max
    loop_mode = getattr(args, 'loop', False)

    # Enhanced startup banner with icons
    console.print()
    banner_title = f"🎬 MagicLight Auto   v{__version__}"
    banner_subtitle = f"🔧 Mode: [bold cyan]{mode.upper()}[/bold cyan]"
    if loop_mode:
        banner_subtitle += f" [yellow]🔄 LOOP[/yellow]"
    banner_subtitle += f"\n📊 Limit: [bold green]{amount if amount > 0 else 'All pending'}[/bold green]"
    
    console.print(Panel(
        banner_subtitle,
        title=banner_title,
        border_style="cyan", 
        padding=(1, 2), 
        expand=False
    ))
    
    # Show configuration status table
    config_status = {
        "📧 Email": "✅ Set" if EMAIL else "❌ Not set",
        "🔑 Password": "✅ Set" if PASSWORD else "❌ Not set",
        "📊 Sheet ID": "✅ Set" if SHEET_ID else "❌ Not set",
        "☁️ Drive Upload": "✅ Enabled" if getattr(args, 'upload_drive', False) else "❌ Disabled",
        "🤖 Headless": "✅ Enabled" if getattr(args, 'headless', False) else "❌ Disabled",
        "🐛 Debug": "✅ Enabled" if DEBUG else "❌ Disabled",
        "💾 Local Output": "✅ Enabled" if LOCAL_OUTPUT_ENABLED else "❌ Disabled"
    }
    
    _show_status_table(config_status)
    console.print()

    if mode == "process":
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        if not vids:
            _warn("No unprocessed videos found in output/")
            return True
        _ok(f"Found {len(vids)} video(s) to process")
        cfg = load_process_cfg()
        process_all(cfg, videos=vids, dry_run=args.dry_run, upload=args.upload_drive,
            upload_youtube=getattr(args, 'upload_youtube', False))
        return True
    elif mode in ["combined", "generate"]:
        os.environ["PIPELINE_MODE"] = mode  # track mode for inline processing guard
        os.environ["RUN_PROCESS_INLINE"] = "1" if mode == "combined" else "0"
        run_once = False
        if loop_mode:
            args.upload_drive = True
            amount = amount if amount > 0 else 1
            if not DRIVE_FOLDER_ID:
                _err("DRIVE_FOLDER_ID required for --loop mode!")
                return False
            if os.environ.get("GITHUB_ACTIONS") == "true":
                os.environ["DRIVE_ONLY_MODE"] = "true"
            run_once = os.environ.get("LOOP_RUN_ONCE", "false").lower() == "true"
        pw_manager = sync_playwright().start()
        _browser = pw_manager.chromium.launch(
            headless=args.headless or loop_mode,
            args=["--start-maximized"]
        )
        try:
            cycle_count = 0
            while True:
                cycle_count += 1
                _credits_used = 0
                console.rule(f"[cyan]Cycle {cycle_count}[/cyan]" if loop_mode else "[cyan]Starting[/cyan]")
                _run_pipeline_core(limit=amount, source_type="auto")
                if not loop_mode:
                    break
                try:
                    for ctx in list(_browser.contexts):
                        try: ctx.close()
                        except: pass
                except: pass
                if run_once and cycle_count >= 1:
                    _ok("[loop] Run-once complete.")
                    break
                sleep_log(30, "loop cooldown")
            return True
        finally:
            try:
                if _browser: _browser.close()
            except: pass
            try: pw_manager.stop()
            except: pass
    return False

if __name__ == "__main__":
    try:
        args = parse_args()
        if getattr(args, 'migrate_schema', False):
            console.print(Panel.fit("[bold cyan]Schema Migration[/bold cyan]", border_style="cyan"))
            ensure_sheet_schema()
            _ok("Done.")
            raise SystemExit(0)
        if not run_cli_mode(args):
            class Args: pass
            args = Args()
            args.headless     = False
            args.upload_drive = False
            menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow][STOP] Exiting...[/bold yellow]")
        if _browser:
            try:
                for context in _browser.contexts:
                    try:
                        for page in context.pages: page.close()
                    except: pass
                    context.close()
                _browser.close()
            except: pass
        import os as _os
        _os._exit(0)
    except Exception as e:
        console.print(f"\n[bold red][FATAL] {e}[/bold red]")
