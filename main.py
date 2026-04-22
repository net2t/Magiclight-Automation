"""
main.py — MagicLight Auto v3.0
================================
Orchestrator: imports all modules and runs the unified pipeline.

Modes (PIPELINE_MODE env / --mode flag):
  local   — generate + process, save locally only
  youtube — generate + process + upload to YouTube + update sheet
  multi   — same as youtube (structured for future expansion)

CLI:
    python main.py                              # Interactive menu
    python main.py --mode local    --max 1
    python main.py --mode youtube  --max 5 --headless
    python main.py --mode combined --loop --headless   # Legacy alias
    python main.py --mode generate                     # Legacy alias
    python main.py --mode process
    python main.py --migrate-schema
    python main.py --check-credits
    python main.py --dashboard                         # Start Flask dashboard
"""

__version__ = "3.0.0"

import os
import re
import sys
import time
import signal
import warnings
import argparse
from pathlib import Path
from datetime import datetime

# ── Suppress warnings ─────────────────────────────────────────────────────────
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

# ── Config (must be first) ────────────────────────────────────────────────────
from config import (
    __version__ as _cfg_ver,
    EMAIL, PASSWORD, OUT_BASE, OUT_SHOTS,
    PIPELINE_MODE as _PIPELINE_MODE_ENV,
    LOCAL_OUTPUT_ENABLED, UPLOAD_TO_DRIVE,
    DRIVE_FOLDER_ID, DOWNLOADS_DIR, PROCESSED_DIR,
    DEBUG, log,
)

# ── Rich console ───────────────────────────────────────────────────────────────
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

console = Console(highlight=False, emoji=False)


def _step(label):  console.print(f"\n[bold cyan]🔧 {label}[/bold cyan]")
def _ok(msg):      console.print(f"  [bold green]✅[/bold green] {msg}")
def _warn(msg):    console.print(f"  [bold yellow]⚠️[/bold yellow]  {msg}")
def _err(msg):     console.print(f"  [bold red]❌[/bold red] {msg}")
def _info(msg):    console.print(f"  [dim]ℹ️[/dim] {msg}")


# ── Module imports ─────────────────────────────────────────────────────────────
from sheets import (
    read_sheet, update_sheet_row, ensure_sheet_schema,
    update_credits_login, update_credits_completion,
    _get_sheet, _actual_sheet_cols, SHEET_SCHEMA,
)
from generator import (
    login, step1, step2, step3, step4,
    _retry_from_user_center, _read_credits_from_page,
    _credit_exhausted, check_all_accounts_credits,
    sleep_log, screenshot, debug_buttons, make_safe, extract_row_num,
    dismiss_popups, make_safe,
    set_shutdown as _gen_set_shutdown,
    set_browser  as _gen_set_browser,
)
from processor import (
    process_video, scan_videos, check_ffmpeg, load_process_cfg,
    process_all, extract_row_num as _proc_extract_row_num,
    cleanup_processed,
)
from uploader import upload_story, is_configured as _yt_configured

# ── Drive upload (legacy optional utility) ─────────────────────────────────────
try:
    from googleapiclient.discovery import build as _gdrive_build
    from googleapiclient.http import MediaFileUpload as _MediaUpload
    _drive_libs = True
except ImportError:
    _drive_libs = False


# ── Global state ──────────────────────────────────────────────────────────────
_shutdown = False
_browser  = None
args      = None   # set by parse_args()


def _set_shutdown(val: bool):
    global _shutdown
    _shutdown = val
    _gen_set_shutdown(val)


# ── Signal handler ────────────────────────────────────────────────────────────
def _sig(sig, frame):
    _warn("[STOP] Ctrl+C — cleaning up…")
    _set_shutdown(True)
    if _browser:
        try: _browser.close()
        except: pass
    import os as _os; _os._exit(1)

signal.signal(signal.SIGINT, _sig)


# ── Drive upload (local utility, not in default pipeline) ─────────────────────
def upload_to_drive(file_path, folder_name=None, max_retries=3) -> str:
    from sheets import _get_credentials
    file_path = str(file_path)
    if not file_path or not os.path.exists(file_path):
        _warn(f"[drive] File not found: {file_path}"); return ""
    if not DRIVE_FOLDER_ID:
        _warn("[drive] DRIVE_FOLDER_ID not set — skipping"); return ""
    if not _drive_libs:
        _warn("[drive] google-api-python-client not installed"); return ""
    file_size_mb = os.path.getsize(file_path) / 1_048_576
    if not folder_name:
        folder_name = Path(file_path).stem.replace("_processed", "").replace("_thumb", "")
    _info(f"[drive] Uploading {os.path.basename(file_path)} ({file_size_mb:.1f} MB)…")
    for attempt in range(max_retries):
        try:
            creds = _get_credentials()
            service = _gdrive_build("drive", "v3", credentials=creds)
            resp = service.files().list(
                q=f"name='{folder_name}' and '{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder'",
                fields="files(id,name)"
            ).execute()
            folder_id = resp["files"][0]["id"] if resp.get("files") else None
            if not folder_id:
                folder = service.files().create(
                    body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder",
                          "parents": [DRIVE_FOLDER_ID]},
                    fields="id"
                ).execute()
                folder_id = folder.get("id")
            media = _MediaUpload(file_path, resumable=True, chunksize=1024 * 1024)
            req = service.files().create(
                body={"name": os.path.basename(file_path), "parents": [folder_id]},
                media_body=media, fields="id,webViewLink"
            )
            response = None
            while response is None:
                status, response = req.next_chunk()
                if status: _info(f"[drive] {int(status.progress()*100)}%")
            link = response.get("webViewLink", "")
            if link: _ok(f"[drive] Uploaded -> {link}"); return link
        except Exception as e:
            if attempt < max_retries - 1:
                _warn(f"[drive] Attempt {attempt+1} failed: {e}"); time.sleep(5 + 2 ** attempt)
            else:
                _err(f"[drive] All attempts failed: {e}"); return ""
    return ""


# ── Core pipeline ─────────────────────────────────────────────────────────────
def _run_pipeline_core(limit: int, pipeline_mode: str = "local"):
    """
    pipeline_mode:
      "local"   — generate + process locally
      "youtube" — generate + process + upload to YouTube
      "multi"   — same as youtube (future expansion ready)
    """
    global _browser

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

    # Load accounts
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

    import random; random.shuffle(accounts)
    account_idx   = 0
    credits_total = 0
    credits_used  = 0

    _ok(f"Processing {len(pending)} stor{'y' if len(pending)==1 else 'ies'}")
    _ok(f"Accounts: {len(accounts)}   Mode: {pipeline_mode.upper()}")

    curr_email, curr_pw = accounts[account_idx]
    os.environ["CURRENT_EMAIL"] = curr_email
    context = _browser.new_context(accept_downloads=True, no_viewport=True)
    page    = context.new_page()
    try:
        credits_total = login(page, custom_email=curr_email, custom_pw=curr_pw)
    except Exception as e:
        _err(f"[FATAL] Login failed for {curr_email}: {e}"); return

    for rec_idx, row in pending:
        if _shutdown: break

        # ── Credit check / account rotation ──────────────────────────────────
        credit_before = 0
        try:
            page.goto("https://magiclight.ai/user-center", timeout=30000)
            page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                   state="visible", timeout=10000)
            credit_before, _ = _read_credits_from_page(page)
        except Exception as ce:
            credit_before = max(0, credits_total - credits_used)

        if credit_before < 70:
            _warn(f"[Rotate] {curr_email} low credits ({credit_before})")
            try:
                if context and not context.is_closed(): context.close()
            except: pass
            account_idx += 1
            if account_idx >= len(accounts):
                _err("All accounts exhausted — stopping."); break
            credits_total = credits_used = 0
            curr_email, curr_pw = accounts[account_idx]
            os.environ["CURRENT_EMAIL"] = curr_email
            _step(f"[Rotate] Switching to {curr_email}")
            rotation_ok = False
            for _ra in range(2):
                try:
                    context = _browser.new_context(accept_downloads=True, no_viewport=True)
                    page    = context.new_page()
                    credits_total = login(page, custom_email=curr_email, custom_pw=curr_pw)
                    credit_before, _ = _read_credits_from_page(page)
                    if credit_before >= 70:
                        _ok(f"[Rotate] Switched -> {curr_email} ({credit_before} credits)")
                        rotation_ok = True; break
                    else:
                        _warn(f"[Rotate] New account also low: {credit_before}")
                        if not context.is_closed(): context.close()
                except Exception as re_err:
                    _warn(f"[Rotate] Attempt {_ra+1} failed: {re_err}")
                    try:
                        if context and not context.is_closed(): context.close()
                    except: pass
                    time.sleep(3)
            if not rotation_ok:
                _err(f"[Rotate] Could not switch to {curr_email}"); break

        # ── Build story text ──────────────────────────────────────────────────
        vals  = list(row.values())
        col_c = str(vals[2]).strip() if len(vals) > 2 else ""
        col_d = str(vals[3]).strip() if len(vals) > 3 else ""
        col_e = str(vals[4]).strip() if len(vals) > 4 else ""
        story = f"{col_c}\n\n{col_d}\n\n{col_e}".strip()
        if not story:
            _warn(f"Row {rec_idx+2}: empty story — skipping"); continue
        title   = str(row.get("Title", f"Row{rec_idx+2}")).strip() or f"Row{rec_idx+2}"
        row_num = rec_idx + 2
        safe    = make_safe(row_num, title, "Generated")

        console.print(Rule(style="cyan"))
        console.print(Panel(
            f"[bold]Row {row_num}[/bold]  {title}\n"
            f"[dim]Account: {curr_email}   Credits: {credit_before}   Mode: {pipeline_mode.upper()}[/dim]",
            border_style="cyan", expand=False, padding=(0, 1)
        ))

        try:
            update_sheet_row(row_num,
                Status        = "Processing",
                Email_Used    = curr_email,
                Credit_Before = str(credit_before) if credit_before else "",
                Created_Time  = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception as se:
            _warn(f"[sheet] Initial write failed: {se}")

        project_url  = ""
        result       = None
        credit_after = 0

        # ── GENERATE ─────────────────────────────────────────────────────────
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
            credits_used += 60
            result = step4(page, safe, sheet_row_num=row_num)

            try:
                page.goto("https://magiclight.ai/user-center", timeout=40000)
                page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                       state="visible", timeout=20000)
                time.sleep(3)
                credit_after, _ = _read_credits_from_page(page)
                credits_total = credit_after
                page.goto("https://magiclight.ai/kids-story/", timeout=30000)
            except Exception as ca_err:
                credit_after = max(0, credit_before - 60)

            update_credits_completion(curr_email, credit_before,
                                      credit_before - credit_after,
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
            try:
                result = _retry_from_user_center(page, project_url, safe)
            except Exception as re_err:
                _warn(f"[retry] {re_err}"); result = None
            if not result:
                update_sheet_row(row_num, Status="Error",
                                 Notes=str(e)[:150],
                                 Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                sleep_log(5); continue

        if not (result and result.get("video")):
            update_sheet_row(row_num, Status="No_Video",
                             Email_Used=curr_email,
                             Notes="Video generation failed",
                             Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            _warn(f"Row {row_num} -> No_Video"); continue

        # ── GENERATED: update sheet ───────────────────────────────────────────
        try:
            update_sheet_row(row_num,
                Status        = "Generated",
                Gen_Title     = result.get("gen_title", ""),
                Gen_Summary   = result.get("summary", "")[:200],
                Gen_Tags      = result.get("tags", ""),
                Project_URL   = project_url,
                Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                Email_Used    = curr_email,
                Credit_Before = str(credit_before),
                Credit_After  = str(credit_after),
                Notes         = f"Generated OK | Credits: {credit_before}->{credit_after}",
            )
        except Exception as se:
            _warn(f"[sheet] Generated write failed: {se}")

        # ── PROCESS ───────────────────────────────────────────────────────────
        video_path = Path(result.get("video", ""))
        thumb_path = result.get("thumb", "")

        if not video_path.exists():
            _warn(f"Row {row_num}: video file missing after generation")
            update_sheet_row(row_num, Status="Generated",
                             Notes="Generated OK but local file missing for processing")
            continue

        _info(f"[pipeline] Processing video for row {row_num}…")
        success, processed_path = process_video(video_path, output_dir=PROCESSED_DIR)
        if not success or not processed_path:
            _warn(f"Row {row_num}: FFmpeg processing failed")
            update_sheet_row(row_num, Status="Error",
                             Notes="FFmpeg processing failed",
                             Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            continue

        try:
            update_sheet_row(row_num,
                Status        = "Processed",
                Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                Notes         = f"Processed: {processed_path.name}",
            )
        except Exception as se:
            _warn(f"[sheet] Processed write failed: {se}")

        # ── UPLOAD (youtube / multi modes only) ───────────────────────────────
        if pipeline_mode in ("youtube", "multi"):
            if not _yt_configured():
                _warn("[uploader] YouTube not configured — skipping upload (set youtube_oauth.json)")
                update_sheet_row(row_num, Status="Processed",
                                 Notes="Processed OK — YouTube upload skipped (not configured)")
            else:
                # Duplicate check: skip if YouTube_URL already filled
                existing_yt = row.get("YouTube_URL", "").strip()
                if existing_yt:
                    _info(f"[uploader] Row {row_num} already uploaded: {existing_yt} — skipping")
                else:
                    yt_title = result.get("gen_title") or title
                    yt_desc  = result.get("summary", "")
                    yt_tags  = result.get("tags", "")

                    _info(f"[uploader] Uploading to YouTube: {yt_title[:50]}…")
                    yt_url = upload_story(
                        video_path    = processed_path,
                        thumb_path    = thumb_path or None,
                        title         = yt_title,
                        description   = yt_desc,
                        tags          = yt_tags,
                    )
                    if yt_url:
                        _ok(f"[uploader] Uploaded -> {yt_url}")
                        try:
                            update_sheet_row(row_num,
                                Status        = "Uploaded",
                                YouTube_URL   = yt_url,
                                Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                Notes         = f"Uploaded to YouTube: {yt_url}",
                            )
                        except Exception as se:
                            _warn(f"[sheet] YouTube URL write failed: {se}")
                        # Clean up processed file after successful upload
                        cleanup_processed(processed_path)
                    else:
                        _err(f"[uploader] Upload failed for row {row_num}")
                        update_sheet_row(row_num, Status="Error",
                                         Notes="YouTube upload failed",
                                         Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        else:
            # local mode — update Drive link if --upload-drive passed
            drive_link = ""
            if getattr(args, "upload_drive", False) or UPLOAD_TO_DRIVE:
                drive_link = upload_to_drive(str(processed_path), processed_path.parent.name)
            actual = _actual_sheet_cols()
            row_update = dict(
                Status         = "Done",
                Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                Notes          = f"Done | Account: {curr_email}",
            )
            if "Process_D_Link" in actual and drive_link:
                row_update["Process_D_Link"] = drive_link
            elif drive_link:
                row_update["Drive_Link"] = drive_link
            try:
                update_sheet_row(row_num, **row_update)
                _ok(f"[sheet] Row {row_num} -> Done")
            except Exception as se:
                _warn(f"[sheet] Done write failed: {se}")

        if len(pending) > 1:
            sleep_log(5, "cooldown")

    try: context.close()
    except: pass
    console.rule(style="cyan")
    _ok("Pipeline sequence complete.")


# ── Menu ──────────────────────────────────────────────────────────────────────
import json as _json
MENU_STATE_FILE = ".menu_state.json"


def load_menu_state():
    try:
        if os.path.exists(MENU_STATE_FILE):
            with open(MENU_STATE_FILE) as f:
                return _json.load(f)
    except Exception: pass
    return {}


def save_menu_state(state):
    try:
        with open(MENU_STATE_FILE, "w") as f:
            _json.dump(state, f)
    except Exception: pass


def show_pending_table():
    try:
        records = read_sheet()
    except Exception as e:
        _warn(f"[sheet] Could not read: {e}"); return 0
    pending = [r for r in records if str(r.get("Status", "")).strip().lower() == "pending"]
    t = Table(title=f"[cyan]Pending Stories ({len(pending)})[/cyan]",
              show_header=True, header_style="bold cyan")
    t.add_column("Row", width=5, style="dim")
    t.add_column("Title", width=35)
    t.add_column("Theme", width=20)
    for i, r in enumerate(pending[:15], start=2):
        t.add_row(str(i), str(r.get("Title", ""))[:35], str(r.get("Theme", ""))[:20])
    if len(pending) > 15:
        t.add_row("…", f"+{len(pending)-15} more", "")
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


def menu():
    global _browser, args
    state = load_menu_state()
    console.print()
    console.print(Panel(
        f"[bold cyan]MagicLight Auto[/bold cyan]   [dim]v{__version__}[/dim]\n"
        f"[dim]Automated Kids Story Video Pipeline[/dim]",
        border_style="cyan", padding=(0, 2), expand=False
    ))
    console.print()
    show_pending_table()
    console.print()

    mt = Table(show_header=False, box=None, padding=(0, 2))
    mt.add_column("num",  style="bold cyan", width=4)
    mt.add_column("name", style="bold white", width=35)
    mt.add_row("1", "Full Pipeline (generate + process + YouTube)")
    mt.add_row("2", "Local Pipeline  (generate + process, no upload)")
    mt.add_row("3", "Video Story Generation only")
    mt.add_row("4", "Video Encoding / FFmpeg Process only")
    mt.add_row("5", "Check Account Credits")
    mt.add_row("6", "Start Dashboard (Flask)")
    mt.add_row("7", "Exit")
    console.print(mt)
    console.print()

    choice = console.input("  [bold cyan]Select Mode [1-7]: [/bold cyan]").strip()
    if choice == "5":
        check_all_accounts_credits(); return
    if choice == "6":
        _info("[dashboard] Starting at http://127.0.0.1:5000")
        import subprocess
        subprocess.Popen([sys.executable, "dashboard.py"])
        _ok("Dashboard started — open http://127.0.0.1:5000"); return
    if choice not in ["1", "2", "3", "4"]:
        return

    mode_map = {"1": "youtube", "2": "local", "3": "generate", "4": "process"}
    mode = mode_map[choice]

    amount = ask_amount("Stories")

    loop_mode = False
    if mode in ("youtube", "local", "generate"):
        lc = console.input("  [bold cyan]🔄 Run on loop (Y/N)? [/bold cyan]").strip().upper()
        loop_mode = (lc == "Y")

    upload_drive_flag = False
    if mode in ("youtube", "local", "generate"):
        ud = console.input("  [bold cyan]☁️ Upload to Google Drive (Y/N)? [/bold cyan]").strip().upper()
        upload_drive_flag = (ud == "Y")

    if not args:
        class _Args: pass
        args = _Args()
    args.upload_drive = upload_drive_flag
    args.headless     = False

    console.print()

    if mode == "process":
        from processor import scan_videos, process_all
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        process_all(vids, dry_run=False)
        return

    # Playwright pipeline
    from playwright.sync_api import sync_playwright
    pw_manager = sync_playwright().start()
    _browser   = pw_manager.chromium.launch(headless=False, args=["--start-maximized"])
    _gen_set_browser(_browser)

    # Map legacy "generate" -> "local" without process step
    pipeline_mode = "local" if mode == "generate" else mode
    run_process = mode not in ("generate",)

    try:
        cycle = 0
        while True:
            cycle += 1
            console.rule(f"[cyan]Cycle {cycle}[/cyan]" if loop_mode else "[cyan]Starting[/cyan]")
            _run_pipeline_core(limit=amount, pipeline_mode=pipeline_mode)
            if not loop_mode: break
            sleep_log(30, "loop cooldown")
    finally:
        try:
            if _browser: _browser.close()
        except: pass
        try: pw_manager.stop()
        except: pass


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description=f"🎬 MagicLight Auto v{__version__} — Kids Story Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode",
        choices=["local", "youtube", "multi", "combined", "generate", "process", "loop"],
        help="Pipeline mode")
    parser.add_argument("--max", type=int, default=0,
        help="Max stories (0=all pending)")
    parser.add_argument("--headless", action="store_true",
        help="Run browser headless")
    parser.add_argument("--upload-drive", action="store_true",
        help="Upload to Google Drive after processing")
    parser.add_argument("--dry-run", action="store_true",
        help="Preview only, no encoding")
    parser.add_argument("--loop", action="store_true",
        help="Infinite loop mode")
    parser.add_argument("--debug", action="store_true",
        help="Verbose debug logging")
    parser.add_argument("--migrate-schema", action="store_true",
        help="Write correct headers to Sheet row 1")
    parser.add_argument("--check-credits", action="store_true",
        help="Check all accounts and log credits")
    parser.add_argument("--dashboard", action="store_true",
        help="Start Flask monitoring dashboard")
    return parser.parse_args()


def run_cli_mode(a) -> bool:
    global _browser, args
    args = a

    if getattr(a, "debug", False):
        os.environ["DEBUG"] = "1"

    if getattr(a, "dashboard", False):
        _info("[dashboard] Starting at http://127.0.0.1:5000")
        from dashboard import app
        from config import DASHBOARD_HOST, DASHBOARD_PORT
        app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, threaded=True)
        return True

    if getattr(a, "check_credits", False):
        check_all_accounts_credits(headless=getattr(a, "headless", False))
        return True

    # Normalise legacy mode aliases
    mode = getattr(a, "mode", None)
    if mode == "loop":       mode = "local"; a.loop = True
    if mode == "combined":   mode = "youtube"    # upgrade alias
    if not mode and (a.max > 0 or a.headless or a.upload_drive):
        mode = "local"
    if not mode:
        return False

    amount    = a.max
    loop_mode = getattr(a, "loop", False)

    # GitHub Actions safety
    if os.environ.get("GITHUB_ACTIONS") == "true":
        a.headless = True

    if mode == "process":
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        if not vids:
            _warn("No unprocessed videos found in output/"); return True
        from processor import process_all
        process_all(vids, dry_run=getattr(a, "dry_run", False))
        return True

    # Browser pipeline
    from playwright.sync_api import sync_playwright
    pw_manager = sync_playwright().start()
    _browser = pw_manager.chromium.launch(
        headless=a.headless or loop_mode,
        args=["--start-maximized"]
    )
    _gen_set_browser(_browser)

    _pipeline_mode = mode if mode in ("local", "youtube", "multi") else "local"

    # Banner
    console.print()
    console.print(Panel(
        f"Mode: [bold cyan]{_pipeline_mode.upper()}[/bold cyan]"
        + (" [yellow]🔄 LOOP[/yellow]" if loop_mode else "")
        + f"\nLimit: [bold green]{amount if amount > 0 else 'All pending'}[/bold green]"
        + f"   Drive: {'✅' if a.upload_drive else '❌'}"
        + f"   YT: {'✅' if _yt_configured() else '❌ (not configured)'}",
        title=f"🎬 MagicLight Auto v{__version__}",
        border_style="cyan", padding=(1, 2), expand=False
    ))

    try:
        cycle = 0
        while True:
            cycle += 1
            console.rule(f"[cyan]Cycle {cycle}[/cyan]" if loop_mode else "[cyan]Starting[/cyan]")
            _run_pipeline_core(limit=amount, pipeline_mode=_pipeline_mode)
            if not loop_mode: break
            if loop_mode and os.environ.get("LOOP_RUN_ONCE", "false").lower() == "true":
                _ok("[loop] Run-once complete."); break
            # Close stale browser contexts between cycles
            try:
                for ctx in list(_browser.contexts):
                    try: ctx.close()
                    except: pass
            except: pass
            sleep_log(30, "loop cooldown")
        return True
    finally:
        try:
            if _browser: _browser.close()
        except: pass
        try: pw_manager.stop()
        except: pass


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        _args = parse_args()
        if getattr(_args, "migrate_schema", False):
            console.print(Panel.fit("[bold cyan]Schema Migration[/bold cyan]", border_style="cyan"))
            ensure_sheet_schema()
            _ok("Done."); raise SystemExit(0)
        if not run_cli_mode(_args):
            args = _args
            menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow][STOP] Exiting…[/bold yellow]")
        if _browser:
            try:
                for ctx in _browser.contexts:
                    try:
                        for pg in ctx.pages: pg.close()
                    except: pass
                    ctx.close()
                _browser.close()
            except: pass
        import os as _os; _os._exit(0)
    except SystemExit:
        raise
    except Exception as e:
        console.print(f"\n[bold red][FATAL] {e}[/bold red]")
        log.exception("Fatal error")
