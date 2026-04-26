"""
MagicLight v2.0 — Process Stage
Reads VideoGen rows with Trigger=PROCESS, runs FFmpeg, writes to Process tab.

Usage:
    python run.py --mode process [--max N] [--dry-run] [--debug]
"""

from utils.sheets import get_process_pending, append_process_row, update_process_row
from utils.helpers import build_processed_path, build_thumbnail_path, now_str
from utils.logger import get_system_logger, get_job_logger
from utils.config import DEFAULT_MAX_JOBS
from stages.process.ffmpeg_utils import process_video, extract_thumbnail

log = get_system_logger("process")


def run_process(max_jobs: int = DEFAULT_MAX_JOBS, dry_run: bool = False, debug: bool = False):
    """
    Main process loop:
      1. Fetch VideoGen rows where Trigger=PROCESS and Status=Generated
      2. Run FFmpeg (add intro/outro, thumbnail)
      3. Append result to Process tab
    """
    log.info(f"[Process] Starting — max_jobs={max_jobs} dry_run={dry_run}")

    rows = get_process_pending()
    if not rows:
        log.info("[Process] No PROCESS rows found — nothing to do.")
        return

    rows = rows[:max_jobs]
    log.info(f"[Process] Found {len(rows)} row(s) to process")

    for row in rows:
        title     = row.get("Title", "")
        gen_title = row.get("Gen_Title", title)
        # Use a generated ID for safe path slugs if missing
        job_id  = row.get("ID") or title.replace(' ', '_')[:20] 
        raw_path  = row.get("Raw_Video_Path", "")
        job_log   = get_job_logger(job_id)

        job_log.info(f"[Process] Processing Title='{title}' — '{gen_title}'")

        # Append Pending row to Process tab
        process_pending = {
            "Status": "Pending",
            "Theme": row.get("Theme", ""),
            "Title": title,
            "Story": row.get("Story", ""),
            "Moral": row.get("Moral", ""),
            "Gen_Title": gen_title,
            "Gen_Summary": row.get("Gen_Summary", ""),
            "Gen_Tags": row.get("Gen_Tags", ""),
            "Project_URL": row.get("Project_URL", ""),
            "Created_Time": row.get("Created_Time", ""),
            "Completed_Time": "",
            "Notes": row.get("Notes", ""),
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
            append_process_row(process_pending)

        if dry_run:
            job_log.info(f"[DRY-RUN] Would process Title={title}")
            continue

        try:
            processed_path  = build_processed_path(job_id, gen_title)
            thumbnail_path  = build_thumbnail_path(job_id, gen_title)

            process_video(raw_path, processed_path, job_id=job_id, job_log=job_log)
            extract_thumbnail(processed_path, thumbnail_path, job_log=job_log)

            # Update Process tab
            update_process_row(title, {
                "Status":               "Processed",
                "Completed_Time":       now_str(),
                "Notes":                f"Processed: {processed_path} | Thumb: {thumbnail_path}",
            })

            # We no longer trigger tracking back to Videogen tab since we use identical tabs. 
            # We keep it simple and just rely on the independent tabs.

            job_log.info(f"[Process] ✓ Title={title} complete")

        except Exception as e:
            job_log.error(f"[Process] ✗ Title={title} FAILED: {e}", exc_info=debug)
            update_process_row(title, {
                "Status": "Failed",
                "Notes":  str(e)[:500],
            })

    log.info("[Process] Stage complete.")
