"""
MagicLight v2.0 — Google Sheets Client
Single interface for reading/writing all tabs: INPUT, VideoGen, Process, YouTube, Credits.
"""

import gspread
from google.oauth2.service_account import Credentials
from utils.config import SERVICE_ACCOUNT_FILE, SHEET_ID
from utils.logger import get_system_logger

log = get_system_logger("sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None
_workbook: gspread.Spreadsheet | None = None


def _get_workbook() -> gspread.Spreadsheet:
    global _client, _workbook
    if _workbook is None:
        creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
        _client = gspread.authorize(creds)
        _workbook = _client.open_by_key(SHEET_ID)
        log.info(f"Connected to Google Sheet: {SHEET_ID}")
    return _workbook


def get_sheet(tab_name: str) -> gspread.Worksheet:
    """Return a worksheet by tab name."""
    return _get_workbook().worksheet(tab_name)


# ─── INPUT tab ────────────────────────────────────────────────────────────────

def get_ready_rows(max_rows: int = 5) -> list[dict]:
    """Return up to max_rows rows from INPUT where Status == 'Ready'."""
    ws = get_sheet("INPUT")
    records = ws.get_all_records()
    ready = [r for r in records if r.get("Status") == "Ready"]
    return ready[:max_rows]


def mark_input_picked(row_index: int):
    """Mark an INPUT row as Picked (1-indexed, including header)."""
    ws = get_sheet("INPUT")
    headers = ws.row_values(1)
    col = headers.index("Status") + 1
    ws.update_cell(row_index, col, "Picked")
    log.debug(f"INPUT row {row_index} → Picked")


# ─── VideoGen tab ─────────────────────────────────────────────────────────────

def append_videogen_row(data: dict):
    """Append a new row to VideoGen with Status=Pending."""
    ws = get_sheet("VideoGen")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"VideoGen ← appended row for ID={data.get('ID')}")


def update_videogen_row(job_id: str, updates: dict):
    """Update specific cells in the VideoGen row matching job_id."""
    _update_row("VideoGen", job_id, updates)


# ─── Process tab ─────────────────────────────────────────────────────────────

def get_process_pending() -> list[dict]:
    """Return VideoGen rows with Trigger == 'PROCESS' and Status == 'Generated'."""
    ws = get_sheet("VideoGen")
    records = ws.get_all_records()
    return [r for r in records if r.get("Trigger") == "PROCESS" and r.get("Status") == "Generated"]


def append_process_row(data: dict):
    ws = get_sheet("Process")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"Process ← appended row for ID={data.get('ID')}")


def update_process_row(job_id: str, updates: dict):
    _update_row("Process", job_id, updates)


# ─── YouTube tab ─────────────────────────────────────────────────────────────

def get_upload_pending() -> list[dict]:
    """Return Process rows with Trigger == 'UPLOAD' and Status == 'Processed'."""
    ws = get_sheet("Process")
    records = ws.get_all_records()
    return [r for r in records if r.get("Trigger") == "UPLOAD" and r.get("Status") == "Processed"]


def append_youtube_row(data: dict):
    ws = get_sheet("YouTube")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"YouTube ← appended row for ID={data.get('ID')}")


def update_youtube_row(job_id: str, updates: dict):
    _update_row("YouTube", job_id, updates)


# ─── Credits tab ─────────────────────────────────────────────────────────────

def get_credits_for_email(email: str) -> dict | None:
    ws = get_sheet("Credits")
    records = ws.get_all_records()
    for r in records:
        if r.get("Email") == email:
            return r
    return None


def update_credits_row(email: str, updates: dict):
    _update_row("Credits", email, updates, id_col="Email")


# ─── Generic Helpers ─────────────────────────────────────────────────────────

def _update_row(tab: str, job_id: str, updates: dict, id_col: str = "ID"):
    """Find the row in `tab` where id_col == job_id and update specified columns."""
    ws = get_sheet(tab)
    headers = ws.row_values(1)
    all_values = ws.get_all_values()

    id_idx = headers.index(id_col)
    for i, row in enumerate(all_values[1:], start=2):  # skip header
        if row[id_idx] == str(job_id):
            for col_name, value in updates.items():
                if col_name in headers:
                    col_num = headers.index(col_name) + 1
                    ws.update_cell(i, col_num, value)
            log.debug(f"{tab} row {i} (ID={job_id}) updated: {updates}")
            return

    log.warning(f"{tab}: row with {id_col}={job_id} not found for update")
