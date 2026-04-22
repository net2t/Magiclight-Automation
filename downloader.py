"""
downloader.py — MagicLight Auto v3.0
======================================
Standalone download utilities: direct URL download with retry + temp management.

The Playwright-based download (_download) is NOT here — it remains in generator.py
since it requires a live browser page. This module handles:
  - HTTP/HTTPS direct URL downloads (retry + exponential backoff)
  - Temp file management (temp/downloads/)
  - Post-success cleanup
"""

import os
import time
import requests
from pathlib import Path
from typing import Optional

from config import DOWNLOADS_DIR, log


# ── Direct URL downloader ─────────────────────────────────────────────────────

def download_to_temp(
    url: str,
    filename: str,
    max_retries: int = 3,
    timeout: int = 180,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> Optional[Path]:
    """
    Download a remote URL to temp/downloads/<filename>.
    Returns the local Path on success, None on failure.
    Retries up to max_retries times with exponential backoff.
    """
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS_DIR / filename

    if dest.exists() and dest.stat().st_size > 10_000:
        log.info(f"[dl] Already cached: {dest.name}")
        return dest

    _headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        _headers.update(headers)

    for attempt in range(max_retries):
        try:
            log.info(f"[dl] Attempt {attempt+1}/{max_retries}: {url[:80]}")
            r = requests.get(
                url, stream=True, timeout=timeout,
                headers=_headers, cookies=cookies or {}
            )
            r.raise_for_status()

            total = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(65_536):
                    if chunk:
                        fh.write(chunk)
                        total += len(chunk)

            if total > 10_000:
                log.info(f"[dl] Downloaded {total // 1024} KB -> {dest.name}")
                return dest
            else:
                log.warning(f"[dl] File too small ({total}B), retrying…")
                try:
                    dest.unlink()
                except Exception:
                    pass

        except requests.RequestException as e:
            log.warning(f"[dl] Attempt {attempt+1} failed: {e}")

        if attempt < max_retries - 1:
            wait = 2 ** attempt
            log.info(f"[dl] Retrying in {wait}s…")
            time.sleep(wait)

    log.error(f"[dl] All {max_retries} attempts failed for: {url[:80]}")
    return None


def list_pending_downloads() -> list[Path]:
    """List all files sitting in temp/downloads/ (not yet processed)."""
    if not DOWNLOADS_DIR.exists():
        return []
    return sorted(
        p for p in DOWNLOADS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}
    )


def cleanup_download(path: Path) -> bool:
    """Delete a temp download file after successful processing/upload."""
    try:
        if path and path.exists():
            path.unlink()
            log.info(f"[dl] Cleaned up: {path.name}")
            return True
    except Exception as e:
        log.warning(f"[dl] Cleanup failed for {path}: {e}")
    return False


def cleanup_all_downloads() -> int:
    """Wipe entire downloads temp directory. Returns number of files removed."""
    removed = 0
    for p in list_pending_downloads():
        if cleanup_download(p):
            removed += 1
    return removed
