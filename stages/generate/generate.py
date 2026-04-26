"""
MagicLight v2.0 — Generate Stage
Reads INPUT rows with Status=Ready, runs VideoGen via Playwright, writes to VideoGen tab.

Usage:
    python run.py --mode generate [--max N] [--headless] [--dry-run] [--debug]
"""

from utils.sheets import get_ready_rows, mark_input_picked, append_videogen_row, update_videogen_row
from utils.helpers import generate_id, build_raw_path, now_str
from utils.logger import get_system_logger, get_job_logger
from utils.config import DEFAULT_MAX_JOBS, HEADLESS
from stages.generate.playwright_logic import run_videogen

log = get_system_logger("generate")


def run_generate(max_jobs: int = DEFAULT_MAX_JOBS, headless: bool = HEADLESS,
                 dry_run: bool = False, debug: bool = False):
    """
    Main generate loop:
      1. Fetch up to max_jobs Ready rows from INPUT
      2. For each: run VideoGen via Playwright
      3. Append result to VideoGen tab
    """
    log.info(f"[Generate] Starting — max_jobs={max_jobs} headless={headless} dry_run={dry_run}")

    rows = get_ready_rows(max_rows=max_jobs)
    if not rows:
        log.info("[Generate] No Ready rows found — nothing to do.")
        return

    log.info(f"[Generate] Found {len(rows)} Ready row(s)")

    for i, row in enumerate(rows):
        job_id = row.get("ID") or generate_id()
        job_log = get_job_logger(job_id)
        title   = row.get("Title", "")
        slug_title = title

        # The sheet row index: header=1, data starts at 2
        # get_ready_rows returns dicts; we need to find the actual row index for update
        # (gspread get_all_records gives us 0-indexed; add 2 for header + 1-based)
        sheet_row_index = i + 2

        job_log.info(f"[Generate] Processing ID={job_id} — '{title}'")

        # Mark as Picked to prevent double-processing
        if not dry_run:
            mark_input_picked(sheet_row_index)

        # Append a Pending row to VideoGen immediately
        # Append a Pending row to VideoGen immediately
        videogen_pending = {
            "Status": "Pending",
            "Theme": row.get("Theme", ""),
            "Title": title,
            "Story": row.get("Story", ""),
            "Moral": row.get("Moral", ""),
            "Gen_Title": "",
            "Gen_Summary": "",
            "Gen_Tags": "",
            "Project_URL": "",
            "Created_Time": now_str(),
            "Completed_Time": "",
            "Notes": "",
            "Drive_Link": "",
            "DriveImg_Link": "",
            "Credit_Before": "",
            "Credit_After": "",
            "Email_Used": "",
            "Credit_Acct": "",
            "Credit_Total": "",
            "Credit_Used": "",
            "Credit_Remaining": "",
            "Process_D_Link": "",
            "YouTube_Link": ""
        }
        if not dry_run:
            append_videogen_row(videogen_pending)

        if dry_run:
            job_log.info(f"[DRY-RUN] Would generate ID={job_id} Title={title}")
            continue

        # Run Playwright automation
        try:
            result = run_videogen(
                job_id=job_id,
                title=title,
                story=row.get("Story", ""),
                moral=row.get("Moral", ""),
                theme=row.get("Theme", ""),
                headless=headless,
                debug=debug,
                job_log=job_log,
            )
            raw_path = build_raw_path(job_id, result.get("gen_title", title))

            update_videogen_row(title, {
                "Gen_Title":       result.get("gen_title", title),
                "Gen_Summary":     result.get("gen_summary", ""),
                "Gen_Tags":        result.get("gen_tags", ""),
                "Project_URL":     result.get("project_url", ""),
                "Status":          "Generated",
                "Notes":           f"Raw_Video_Path: {raw_path}",
            })
            job_log.info(f"[Generate] ✓ ID={job_id} complete — trigger=PROCESS")

        except Exception as e:
            job_log.error(f"[Generate] ✗ ID={job_id} Title={title} FAILED: {e}", exc_info=debug)
            update_videogen_row(title, {
                "Status": "Failed",
                "Notes":  str(e)[:500],
            })

    log.info("[Generate] Stage complete.")
