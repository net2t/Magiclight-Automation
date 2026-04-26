#!/usr/bin/env python3
"""
MagicLight v2.0 — Control Center
Entry point for all pipeline stages.

Usage examples:
    python run.py --mode generate
    python run.py --mode process
    python run.py --mode upload --upload-youtube
    python run.py --mode combined --max 3 --headless --loop
    python run.py --mode generate --dry-run --debug
    python run.py --check-credits
"""

import argparse
import sys
import time
from utils.logger import get_system_logger

log = get_system_logger("run")


# ─── Argument Parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MagicLight v2.0 — Automated Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--mode",
        choices=["generate", "process", "upload", "combined"],
        help="Pipeline stage to run.",
    )

    # Quantity / behaviour
    p.add_argument("--max",      type=int, default=5,    metavar="N",  help="Max jobs per run (default: 5)")
    p.add_argument("--headless", action="store_true",                  help="Run browser in headless mode")
    p.add_argument("--loop",     action="store_true",                  help="Loop indefinitely, sleeping 60s between runs")

    # Upload targets
    p.add_argument("--upload-drive",   action="store_true", help="Upload processed videos to Google Drive")
    p.add_argument("--upload-youtube", action="store_true", help="Upload processed videos to YouTube (default for upload mode)")

    # Dev / debug
    p.add_argument("--dry-run",  action="store_true", help="Simulate without making sheet changes")
    p.add_argument("--debug",    action="store_true", help="Enable verbose debug logging + screenshots")

    # Utility commands
    p.add_argument("--check-credits",   action="store_true", help="Report remaining VideoGen credits for all accounts")
    p.add_argument("--migrate-schema",  action="store_true", help="Ensure all Sheet tabs have correct headers")

    return p


# ─── Stage Runners ────────────────────────────────────────────────────────────

def do_generate(args):
    from stages.generate.generate import run_generate
    run_generate(
        max_jobs=args.max,
        headless=args.headless,
        dry_run=args.dry_run,
        debug=args.debug,
    )


def do_process(args):
    from stages.process.process import run_process
    run_process(
        max_jobs=args.max,
        dry_run=args.dry_run,
        debug=args.debug,
    )


def do_upload(args):
    from stages.upload.upload import run_upload
    # Default: enable YouTube upload unless explicitly disabled
    upload_yt = args.upload_youtube or (not args.upload_drive)
    run_upload(
        max_jobs=args.max,
        upload_youtube=upload_yt,
        upload_drive=args.upload_drive,
        dry_run=args.dry_run,
        debug=args.debug,
    )


def do_combined(args):
    """Run generate → process → upload sequentially in one pass."""
    log.info("[Combined] Running full pipeline: generate → process → upload")
    do_generate(args)
    do_process(args)
    do_upload(args)


# ─── Utility Commands ─────────────────────────────────────────────────────────

def do_check_credits():
    """Print remaining credits for all accounts listed in magilight_accounts.txt."""
    from utils.config import ACCOUNTS_FILE
    from utils.sheets import get_credits_for_email

    if not ACCOUNTS_FILE.exists():
        log.error(f"Accounts file not found: {ACCOUNTS_FILE}")
        return

    emails = []
    for line in ACCOUNTS_FILE.read_text().splitlines():
        line = line.strip()
        if ":" in line:
            emails.append(line.split(":")[0])

    log.info(f"[Credits] Checking {len(emails)} account(s)...")
    for email in emails:
        row = get_credits_for_email(email)
        if row:
            log.info(
                f"  {email}: remaining={row.get('Remaining','?')} "
                f"used={row.get('Used_Credits','?')} "
                f"total={row.get('Total_Credits','?')}"
            )
        else:
            log.warning(f"  {email}: not found in Credits tab")


def do_migrate_schema():
    """Ensure all Sheet tabs have the correct header rows, creating them if necessary."""
    from utils.sheets import _get_workbook
    from gspread.exceptions import WorksheetNotFound

    wb = _get_workbook()

    HEADERS = {
        "Phase1":    ["ID", "Theme", "Title", "Story", "Moral", "Status"],
        "Phase2": ["ID", "Title", "Theme", "Story", "Moral", "Gen_Title", "Gen_Summary",
                     "Gen_Tags", "Project_URL", "Raw_Video_Path", "Status", "Trigger",
                     "Notes", "Created_Time"],
        "Phase3":  ["ID", "Gen_Title", "Raw_Video_Path", "Processed_Video_Path",
                     "Thumbnail_Path", "Status", "Trigger", "Notes", "Completed_Time"],
        "Phase4":  ["ID", "Gen_Title", "Gen_Summary", "Gen_Tags", "Processed_Video_Path",
                     "Thumbnail_Path", "Drive_Link", "YouTube_Link", "Status", "Notes",
                     "Completed_Time"],
        "Credits":  ["Email", "Total_Credits", "Used_Credits", "Remaining",
                     "Last_Checked", "Log_Timestamp", "Log_Detail"],
    }

    for tab, headers in HEADERS.items():
        try:
            ws = wb.worksheet(tab)
            log.info(f"[Schema] {tab}: ✓ tab exists")
        except WorksheetNotFound:
            ws = wb.add_worksheet(title=tab, rows="1000", cols="20")
            log.info(f"[Schema] {tab}: + created new tab")

        try:
            existing = ws.row_values(1)
        except Exception:
            existing = []
            
        if existing == headers:
            log.info(f"[Schema] {tab}: ✓ headers OK")
        else:
            ws.update("A1", [headers])
            log.info(f"[Schema] {tab}: ✓ headers written")


# ─── Main ─────────────────────────────────────────────────────────────────────

DISPATCH = {
    "generate": do_generate,
    "process":  do_process,
    "upload":   do_upload,
    "combined": do_combined,
}


def main():
    parser = build_parser()
    args   = parser.parse_args()

    # Utility commands (no --mode required)
    if args.check_credits:
        do_check_credits()
        return
    if args.migrate_schema:
        do_migrate_schema()
        return

    if not args.mode:
        parser.print_help()
        sys.exit(1)

    runner = DISPATCH[args.mode]

    if args.loop:
        log.info(f"[run] Loop mode ON — running '{args.mode}' every 60 seconds (Ctrl+C to stop)")
        while True:
            try:
                runner(args)
            except KeyboardInterrupt:
                log.info("[run] Loop stopped by user.")
                break
            except Exception as e:
                log.error(f"[run] Unhandled error in loop: {e}", exc_info=args.debug)
            log.info("[run] Sleeping 60s...")
            time.sleep(60)
    else:
        runner(args)


if __name__ == "__main__":
    main()
