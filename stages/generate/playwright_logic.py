"""
MagicLight v2.0 — Playwright Logic (Generate Stage)
Handles browser automation against VideoGen to create videos.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, BrowserContext
from utils.config import VIDEOGEN_URL, PLAYWRIGHT_SESSION, CRED_GENERATE
from utils.helpers import build_raw_path


def run_videogen(
    job_id: str,
    title: str,
    story: str,
    moral: str,
    theme: str = "",
    headless: bool = True,
    debug: bool = False,
    job_log=None,
) -> dict:
    """
    Automate VideoGen to create a video for the given inputs.

    Returns:
        dict with keys: gen_title, gen_summary, gen_tags, project_url, raw_video_path
    """
    from logging import getLogger
    log = job_log or getLogger("playwright")

    log.info(f"[Playwright] Launching browser — headless={headless}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        # Load saved session if available
        storage_state = str(PLAYWRIGHT_SESSION) if PLAYWRIGHT_SESSION.exists() else None
        ctx: BrowserContext = browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
        )
        page: Page = ctx.new_page()

        try:
            # ── Navigate to VideoGen ────────────────────────────────────────
            log.info(f"[Playwright] Navigating to {VIDEOGEN_URL}")
            page.goto(VIDEOGEN_URL, wait_until="networkidle", timeout=60_000)

            # ── Login check ────────────────────────────────────────────────
            _handle_login(page, log)

            # ── Create new project ─────────────────────────────────────────
            log.info(f"[Playwright] Creating project for: {title}")
            project_url = _create_project(page, title, story, moral, theme, log)

            # ── Wait for video to render & download ────────────────────────
            raw_path = build_raw_path(job_id, title)
            _download_video(page, raw_path, log)

            # ── Save session ───────────────────────────────────────────────
            ctx.storage_state(path=str(PLAYWRIGHT_SESSION))
            log.info("[Playwright] Session saved")

            return {
                "gen_title":    title,
                "gen_summary":  f"A children's story about {title}.",
                "gen_tags":     theme,
                "project_url":  project_url,
                "raw_video_path": raw_path,
            }

        finally:
            if debug:
                page.screenshot(path=f"logs/debug_{job_id}.png")
            browser.close()


# ─── Private Helpers ──────────────────────────────────────────────────────────

def _handle_login(page: Page, log):
    """Check if we need to log in and handle it using accounts file."""
    if "login" in page.url or "signin" in page.url:
        log.info("[Playwright] Login required — reading accounts file")
        accounts_file = CRED_GENERATE / "magilight_accounts.txt"
        if not accounts_file.exists():
            raise FileNotFoundError(f"Accounts file not found: {accounts_file}")

        lines = accounts_file.read_text().splitlines()
        for line in lines:
            line = line.strip()
            if not line or ":" not in line:
                continue
            email, password = line.split(":", 1)
            try:
                page.fill("input[type='email']", email)
                page.fill("input[type='password']", password)
                page.click("button[type='submit']")
                page.wait_for_load_state("networkidle", timeout=30_000)
                if "login" not in page.url:
                    log.info(f"[Playwright] Logged in as {email}")
                    return
            except Exception as e:
                log.warning(f"[Playwright] Login failed for {email}: {e}")
        raise RuntimeError("All accounts failed to log in")


def _create_project(page: Page, title: str, story: str, moral: str, theme: str, log) -> str:
    """
    Create a new VideoGen project.
    TODO: Fill in the actual selectors once VideoGen UI is mapped.
    Returns the project URL.
    """
    # Placeholder — implement actual VideoGen selectors here
    log.info("[Playwright] _create_project — implement selectors")
    time.sleep(2)
    return page.url


def _download_video(page: Page, dest_path: str, log):
    """
    Wait for video render to complete and download to dest_path.
    TODO: Fill in the actual download trigger and wait logic.
    """
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    log.info(f"[Playwright] _download_video → {dest_path} — implement download logic")
    # Placeholder: actual download logic goes here
