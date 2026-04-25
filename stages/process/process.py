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
        job_id  = row.get("ID", "")
        gen_title = row.get("Gen_Title") or row.get("Title", "")
        raw_path  = row.get("Raw_Video_Path", "")
        job_log   = get_job_logger(job_id)

        job_log.info(f"[Process] Processing ID={job_id} — '{gen_title}'")

        # Append Pending row to Process tab
        process_pending = {
            "ID":                  job_id,
            "Gen_Title":           gen_title,
            "Raw_Video_Path":      raw_path,
            "Processed_Video_Path":"",
            "Thumbnail_Path":      "",
            "Status":              "Pending",
            "Trigger":             "",
            "Notes":               "",
            "Completed_Time":      "",
        }
        if not dry_run:
            append_process_row(process_pending)

        if dry_run:
            job_log.info(f"[DRY-RUN] Would process ID={job_id}")
            continue

        try:
            processed_path  = build_processed_path(job_id, gen_title)
            thumbnail_path  = build_thumbnail_path(job_id, gen_title)

            process_video(raw_path, processed_path, job_id=job_id, job_log=job_log)
            extract_thumbnail(processed_path, thumbnail_path, job_log=job_log)

            # Update Process tab
            update_process_row(job_id, {
                "Processed_Video_Path": processed_path,
                "Thumbnail_Path":       thumbnail_path,
                "Status":               "Processed",
                "Trigger":              "UPLOAD",
                "Completed_Time":       now_str(),
            })

            # Clear trigger on VideoGen row so it's not re-picked
            from utils.sheets import update_videogen_row
            update_videogen_row(job_id, {"Trigger": "DONE"})

            job_log.info(f"[Process] ✓ ID={job_id} complete — trigger=UPLOAD")

        except Exception as e:
            job_log.error(f"[Process] ✗ ID={job_id} FAILED: {e}", exc_info=debug)
            update_process_row(job_id, {
                "Status": "Failed",
                "Notes":  str(e)[:500],
            })

    log.info("[Process] Stage complete.")
