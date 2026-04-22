"""
sheets.py — MagicLight Auto v3.0
==================================
Google Sheets CRUD, schema management, and Credits sheet helpers.
All Google API auth lives here.
"""

import os
import threading
from datetime import datetime
from config import (
    SHEET_ID, SHEET_NAME, CREDS_JSON, log, DEBUG
)

import gspread
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ── Module state ──────────────────────────────────────────────────────────────
_gc   = None
_ws   = None
_hdr  = []
_cws  = None
_lock = threading.Lock()

CREDIT_PER_GEN = 60

# ── Sheet Schema ──────────────────────────────────────────────────────────────
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
    "Credit_Remaining": 21,  # U
    "Process_D_Link":  22,   # V  ← new
    "YouTube_URL":     23,   # W  ← new
}


# ── Auth ──────────────────────────────────────────────────────────────────────
def _get_service_account_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    if not os.path.exists(CREDS_JSON):
        raise FileNotFoundError(f"Service account credentials not found: {CREDS_JSON}")
    return ServiceAccountCredentials.from_service_account_file(CREDS_JSON, scopes=scopes)


def _get_oauth_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
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
        except Exception:       # fixed: was bare except
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(oauth_file, scopes)
        creds = flow.run_local_server(port=8080, access_type="offline", prompt="consent")
        with open(token_file, "w") as token:
            token.write(creds.to_json())
    return creds


def _get_credentials():
    try:
        if os.path.exists("oauth_credentials.json"):
            return _get_oauth_credentials()
    except Exception:           # fixed: was bare except
        pass
    return _get_service_account_credentials()


# ── Sheet connection ───────────────────────────────────────────────────────────
def _get_sheet():
    global _gc, _ws, _hdr
    if _ws is not None:
        return _ws
    if not SHEET_ID:
        raise ValueError(f"SHEET_ID not set in .env")
    creds = _get_credentials()
    _gc = gspread.authorize(creds)
    sh  = _gc.open_by_key(SHEET_ID)
    _ws = sh.worksheet(SHEET_NAME)
    _hdr = _ws.row_values(1)
    return _ws


def read_sheet() -> list[dict]:
    ws = _get_sheet()
    return ws.get_all_records(head=1)


def _col(name: str) -> int | None:
    return SHEET_SCHEMA.get(name)


def _actual_sheet_cols() -> set:
    """Return set of column names that actually exist in row 1 of the sheet."""
    try:
        _get_sheet()
        return set(h.strip() for h in _hdr if h.strip())
    except Exception:
        return set(SHEET_SCHEMA.keys())


def update_sheet_row(sheet_row_num: int, **kw):
    """Thread-safe, retry-backed cell writer."""
    if not kw:
        return
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with _lock:
                ws = _get_sheet()
                actual_cols = _actual_sheet_cols()
                valid = []
                for col_name, value in kw.items():
                    col_idx = _col(col_name)
                    if col_idx is None:
                        log.debug(f"[sheet] IGNORED unknown col '{col_name}'")
                        continue
                    if col_name not in actual_cols:
                        log.debug(f"[sheet] SKIPPED '{col_name}' — not in sheet headers")
                        continue
                    valid.append((col_name, col_idx, value))
                if not valid:
                    log.warning(f"[sheet] No valid columns to update for row {sheet_row_num}")
                    return
                for col_name, col_idx, value in valid:
                    try:
                        ws.update_cell(sheet_row_num, col_idx,
                                       str(value) if value is not None else "")
                        log.debug(f"[sheet] Row {sheet_row_num} '{col_name}'={str(value)[:40]}")
                    except Exception as cell_e:
                        log.warning(f"[sheet] Cell update failed for {col_name}: {cell_e}")
                return  # success
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"[sheet] Attempt {attempt+1} failed: {e}, retrying…")
                import time; time.sleep(2 ** attempt)
                global _ws, _gc
                _ws = None; _gc = None
            else:
                log.error(f"[sheet] All attempts failed for row {sheet_row_num}: {e}")


def ensure_sheet_schema():
    """Write correct headers to row 1 (run once / migrate)."""
    ws = _get_sheet()
    headers = [""] * max(SHEET_SCHEMA.values())
    for name, idx in SHEET_SCHEMA.items():
        headers[idx - 1] = name
    end_col = chr(ord("A") + len(headers) - 1)
    ws.update(f"A1:{end_col}1", [headers])
    log.info(f"[schema] Headers written to row 1 (A–{end_col})")


# ── Credits sheet ─────────────────────────────────────────────────────────────
def ensure_credits_sheet():
    global _gc, _cws
    if _cws is not None:
        return _cws
    _get_sheet()
    sh = _gc.open_by_key(SHEET_ID)
    try:
        _cws = sh.worksheet("Credits")
    except Exception:
        log.info("[credits] Creating Credits sheet…")
        _cws = sh.add_worksheet(title="Credits", rows="500", cols="10")
        _cws.update("A1:G1", [["Email", "Total_Credits", "Used_Credits",
                                "Remaining", "Last_Checked",
                                "Log_Timestamp", "Log_Detail"]])
        log.info("[credits] Credits sheet created")
    return _cws


def update_credits_login(email: str, total: int):
    try:
        ws = ensure_credits_sheet()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = ws.get_all_values()
        found_row = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0].strip().lower() == email.strip().lower():
                found_row = i; break
        data = [email, str(total), "", "", now_str]
        if found_row:
            ws.update(f"A{found_row}:E{found_row}", [data])
        else:
            ws.append_row(data)
    except Exception as e:
        log.warning(f"[credits] Login update error: {e}")


def update_credits_completion(email: str, total: int, used: int,
                               row_num: int, action: str, status: str):
    """Update Credits sheet with post-generation data (thread-safe, 3 retries)."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with _lock:
                ws = ensure_credits_sheet()
                remaining = max(0, total - used)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if not email or not isinstance(email, str):
                    log.warning(f"[credits] Invalid email: {email}"); return
                if not isinstance(total, (int, float)) or total < 0:
                    log.warning(f"[credits] Invalid total: {total}"); return
                if not isinstance(used, (int, float)) or used < 0:
                    log.warning(f"[credits] Invalid used: {used}"); return
                rows = ws.get_all_values()
                found_row = None
                for i, row in enumerate(rows[1:], start=2):
                    if row and row[0].strip().lower() == email.strip().lower():
                        found_row = i; break
                detail = f"{action} | Row:{row_num} | Status:{status}"
                if found_row:
                    ws.update(f"C{found_row}:G{found_row}",
                              [[str(used), str(remaining), now_str, detail]])
                else:
                    ws.append_row([email, str(total), str(used), str(remaining),
                                   now_str, now_str, detail])
                return
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"[credits] Attempt {attempt+1} failed: {e}, retrying…")
                import time; time.sleep(2 ** attempt)
                global _cws, _gc
                _cws = None; _gc = None
            else:
                log.error(f"[credits] All attempts failed for {email}: {e}")


def get_sheet_gc():
    """Return (gc, spreadsheet) — used by uploader duplicate check."""
    _get_sheet()
    return _gc
