"""
MagicLight v2.0 — Google Sheets Client
Single interface for reading/writing all tabs: Phase1, Phase2, Phase3, Phase4, Credits.
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


# ─── Phase1 tab ────────────────────────────────────────────────────────────────

def get_ready_rows(max_rows: int = 5) -> list[dict]:
    """Return up to max_rows rows from Phase1 where Status == 'Ready'."""
    ws = get_sheet("Phase1")
    records = ws.get_all_records()
    ready = [r for r in records if r.get("Status") == "Ready"]
    return ready[:max_rows]


def mark_input_picked(row_index: int):
    """Mark an Phase1 row as Picked (1-indexed, including header)."""
    ws = get_sheet("Phase1")
    headers = ws.row_values(1)
    col = headers.index("Status") + 1
    ws.update_cell(row_index, col, "Picked")
    log.debug(f"Phase1 row {row_index} → Picked")


# ─── Phase2 tab ─────────────────────────────────────────────────────────────

def append_videogen_row(data: dict):
    """Append a new row to Phase2 with Status=Pending."""
    ws = get_sheet("Phase2")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"Phase2 ← appended row for ID={data.get('ID')}")


def update_videogen_row(job_id: str, updates: dict):
    """Update specific cells in the Phase2 row matching job_id."""
    _update_row("Phase2", job_id, updates)


# ─── Phase3 tab ─────────────────────────────────────────────────────────────

def get_process_pending() -> list[dict]:
    """Return Phase2 rows with Trigger == 'PROCESS' and Status == 'Generated'."""
    ws = get_sheet("Phase2")
    records = ws.get_all_records()
    return [r for r in records if r.get("Trigger") == "PROCESS" and r.get("Status") == "Generated"]


def append_process_row(data: dict):
    ws = get_sheet("Phase3")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"Phase3 ← appended row for ID={data.get('ID')}")


def update_process_row(job_id: str, updates: dict):
    _update_row("Phase3", job_id, updates)


# ─── Phase4 tab ─────────────────────────────────────────────────────────────

def get_upload_pending() -> list[dict]:
    """Return Phase3 rows with Trigger == 'UPLOAD' and Status == 'Processed'."""
    ws = get_sheet("Phase3")
    records = ws.get_all_records()
    return [r for r in records if r.get("Trigger") == "UPLOAD" and r.get("Status") == "Processed"]


def append_youtube_row(data: dict):
    ws = get_sheet("Phase4")
    headers = ws.row_values(1)
    row = [data.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.debug(f"Phase4 ← appended row for ID={data.get('ID')}")


def update_youtube_row(job_id: str, updates: dict):
    _update_row("Phase4", job_id, updates)


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
