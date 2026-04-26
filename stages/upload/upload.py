"""
MagicLight v2.0 — Upload Stage
Reads Process rows with Trigger=UPLOAD, uploads to YouTube + Drive, writes to YouTube tab.

Usage:
    python run.py --mode upload [--max N] [--upload-youtube] [--upload-drive] [--dry-run] [--debug]
"""

from utils.sheets import get_upload_pending, append_youtube_row, update_youtube_row
from utils.helpers import now_str
from utils.logger import get_system_logger, get_job_logger
from utils.config import DEFAULT_MAX_JOBS

log = get_system_logger("upload")


def run_upload(
    max_jobs: int = DEFAULT_MAX_JOBS,
    upload_youtube: bool = True,
    upload_drive: bool = False,
    dry_run: bool = False,
    debug: bool = False,
):
    """
    Main upload loop:
      1. Fetch Process rows where Trigger=UPLOAD and Status=Processed
      2. Upload to YouTube and/or Drive
      3. Append result to YouTube tab
    """
    log.info(
        f"[Upload] Starting — max_jobs={max_jobs} "
        f"youtube={upload_youtube} drive={upload_drive} dry_run={dry_run}"
    )

    rows = get_upload_pending()
    if not rows:
        log.info("[Upload] No UPLOAD rows found — nothing to do.")
        return

    rows = rows[:max_jobs]
    log.info(f"[Upload] Found {len(rows)} row(s) to upload")

    for row in rows:
        title         = row.get("Title", "")
        gen_title     = row.get("Gen_Title", title)
        # Use a generated ID for safe path slugs if missing
        job_id        = row.get("ID") or title.replace(' ', '_')[:20] 
        gen_summary   = row.get("Gen_Summary", "")
        gen_tags      = row.get("Gen_Tags", "")
        proc_path     = row.get("Processed_Video_Path", "")
        thumb_path    = row.get("Thumbnail_Path", "")
        job_log       = get_job_logger(job_id)

        job_log.info(f"[Upload] Uploading Title='{title}' — '{gen_title}'")

        # Append Pending to YouTube tab
        yt_pending = {
            "Status": "Pending",
            "Theme": row.get("Theme", ""),
            "Title": title,
            "Story": row.get("Story", ""),
            "Moral": row.get("Moral", ""),
            "Gen_Title": gen_title,
            "Gen_Summary": gen_summary,
            "Gen_Tags": gen_tags,
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
            "Process_D_Link": proc_path,
            "YouTube_Link": ""
        }
        if not dry_run:
            append_youtube_row(yt_pending)

        if dry_run:
            job_log.info(f"[DRY-RUN] Would upload Title={title}")
            continue

        youtube_link = ""
        drive_link   = ""

        try:
            if upload_youtube:
                from stages.upload.youtube import upload_to_youtube
                youtube_link = upload_to_youtube(
                    video_path=proc_path,
                    thumb_path=thumb_path,
                    title=gen_title,
                    description=gen_summary,
                    tags=gen_tags,
                    job_log=job_log,
                )

            if upload_drive:
                from stages.upload.drive import upload_to_drive
                drive_link = upload_to_drive(
                    file_path=proc_path,
                    folder_name="MagicLight-Videos",
                    job_log=job_log,
                )

            # Update YouTube tab to Done
            update_youtube_row(title, {
                "YouTube_Link":   youtube_link,
                "Drive_Link":     drive_link,
                "Status":         "Done",
                "Completed_Time": now_str(),
            })

            # We keep modular stages independent, so no triggering backward updates here.

            job_log.info(f"[Upload] ✓ Title={title} complete — YouTube={youtube_link}")

        except Exception as e:
            job_log.error(f"[Upload] ✗ Title={title} FAILED: {e}", exc_info=debug)
            update_youtube_row(title, {
                "Status": "Failed",
                "Notes":  str(e)[:500],
            })

    log.info("[Upload] Stage complete.")
