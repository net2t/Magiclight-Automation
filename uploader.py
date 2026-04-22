"""
uploader.py — MagicLight Auto v3.0
=====================================
YouTube Data API v3 upload module.

Features:
  - OAuth 2.0 authentication (token cached in youtube_token.json)
  - Resumable chunked upload (1 MB chunks)
  - Thumbnail upload
  - Duplicate check by title before upload
  - Returns full YouTube URL on success

Usage:
    from uploader import upload_story
    yt_url = upload_story(video_path, thumb_path, title, description, tags)
"""

import os
import json
import time
import http.client
import httplib2
from pathlib import Path
from typing import Optional

from config import (
    YOUTUBE_OAUTH_FILE, YOUTUBE_TOKEN_FILE,
    YOUTUBE_DEFAULT_CATEGORY, YOUTUBE_DEFAULT_PRIVACY,
    log,
)

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    _YT_LIBS_OK = True
except ImportError:
    _YT_LIBS_OK = False
    log.warning("[uploader] google-api-python-client not installed — YouTube upload disabled")

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube"]
CHUNK_SIZE = 1024 * 1024   # 1 MB
MAX_RETRIES = 3


# ── Auth ──────────────────────────────────────────────────────────────────────
def authenticate_youtube():
    """
    Return an authorized YouTube API Resource.
    Caches token in YOUTUBE_TOKEN_FILE.
    Raises FileNotFoundError if YOUTUBE_OAUTH_FILE is missing.
    """
    if not _YT_LIBS_OK:
        raise ImportError("google-api-python-client is required for YouTube upload.")

    if not os.path.exists(YOUTUBE_OAUTH_FILE):
        raise FileNotFoundError(
            f"YouTube OAuth credentials not found: {YOUTUBE_OAUTH_FILE}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    creds = None
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, YOUTUBE_SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_OAUTH_FILE, YOUTUBE_SCOPES)
        creds = flow.run_local_server(port=8090, access_type="offline", prompt="consent")
        with open(YOUTUBE_TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        log.info(f"[uploader] YouTube token saved -> {YOUTUBE_TOKEN_FILE}")

    return build("youtube", "v3", credentials=creds)


# ── Duplicate check ───────────────────────────────────────────────────────────
def check_duplicate(yt, title: str) -> Optional[str]:
    """
    Search the authenticated channel for a video with exact title.
    Returns video_id if found, None otherwise.
    """
    try:
        resp = yt.search().list(
            part="snippet",
            forMine=True,
            type="video",
            q=title,
            maxResults=10
        ).execute()
        for item in resp.get("items", []):
            if item["snippet"]["title"].strip().lower() == title.strip().lower():
                vid_id = item["id"]["videoId"]
                log.info(f"[uploader] Duplicate found: {title} -> {vid_id}")
                return vid_id
    except Exception as e:
        log.warning(f"[uploader] Duplicate check failed: {e}")
    return None


# ── Upload video ──────────────────────────────────────────────────────────────
def upload_video(
    yt,
    video_path: str | Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str | None = None,
    privacy: str | None = None,
) -> str:
    """
    Upload video_path to YouTube using resumable chunked upload.
    Returns YouTube video_id on success.
    Raises Exception on failure.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    _cat  = category_id or YOUTUBE_DEFAULT_CATEGORY
    _priv = privacy or YOUTUBE_DEFAULT_PRIVACY

    body = {
        "snippet": {
            "title":       title[:100],      # YouTube max
            "description": description[:5000],
            "tags":        tags or [],
            "categoryId":  _cat,
        },
        "status": {
            "privacyStatus":          _priv,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=CHUNK_SIZE,
    )

    request = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    log.info(f"[uploader] Uploading: {video_path.name} ({video_path.stat().st_size // 1_048_576} MB)")

    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                log.info(f"[uploader] Upload progress: {pct}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504):
                retry += 1
                if retry > MAX_RETRIES:
                    raise Exception(f"YouTube upload failed after {MAX_RETRIES} retries: {e}")
                wait = 2 ** retry
                log.warning(f"[uploader] HTTP {e.resp.status} — retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise
        except (http.client.HTTPException, httplib2.HttpLib2Error, Exception) as e:
            retry += 1
            if retry > MAX_RETRIES:
                raise Exception(f"YouTube upload network error after {MAX_RETRIES} retries: {e}")
            wait = 2 ** retry
            log.warning(f"[uploader] Network error — retrying in {wait}s: {e}")
            time.sleep(wait)

    video_id = response.get("id")
    if not video_id:
        raise Exception(f"YouTube upload returned no video ID: {response}")

    log.info(f"[uploader] Uploaded -> https://www.youtube.com/watch?v={video_id}")
    return video_id


# ── Upload thumbnail ──────────────────────────────────────────────────────────
def set_thumbnail(yt, video_id: str, thumb_path: str | Path) -> bool:
    """
    Upload a custom thumbnail for a YouTube video.
    Returns True on success, False on failure.
    """
    thumb_path = Path(thumb_path)
    if not thumb_path.exists():
        log.warning(f"[uploader] Thumbnail not found: {thumb_path}")
        return False

    ext     = thumb_path.suffix.lower()
    mime    = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    media   = MediaFileUpload(str(thumb_path), mimetype=mime, resumable=False)

    try:
        yt.thumbnails().set(videoId=video_id, media_body=media).execute()
        log.info(f"[uploader] Thumbnail set for {video_id}")
        return True
    except HttpError as e:
        log.warning(f"[uploader] Thumbnail upload failed: {e}")
        return False


# ── High-level convenience ────────────────────────────────────────────────────
def upload_story(
    video_path: str | Path,
    thumb_path: str | Path | None,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    skip_duplicate_check: bool = False,
) -> str:
    """
    Full flow:
      1. Authenticate YouTube
      2. Check duplicate (unless skip_duplicate_check=True)
      3. Upload video (resumable, chunked)
      4. Set thumbnail
      5. Return full YouTube URL

    Returns "" on failure.
    """
    if not _YT_LIBS_OK:
        log.error("[uploader] YouTube libraries missing — install google-api-python-client")
        return ""

    try:
        yt = authenticate_youtube()
    except FileNotFoundError as e:
        log.error(f"[uploader] Auth failed: {e}")
        return ""
    except Exception as e:
        log.error(f"[uploader] Auth error: {e}")
        return ""

    # Duplicate check
    if not skip_duplicate_check:
        existing_id = check_duplicate(yt, title)
        if existing_id:
            yt_url = f"https://www.youtube.com/watch?v={existing_id}"
            log.info(f"[uploader] Skipping duplicate — returning existing: {yt_url}")
            return yt_url

    # Parse tags from hashtag string if necessary
    tag_list = tags
    if isinstance(tags, str):
        tag_list = [t.strip().lstrip("#") for t in tags.split() if t.strip()]

    for attempt in range(MAX_RETRIES):
        try:
            video_id = upload_video(yt, video_path, title, description, tag_list)
            break
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                log.warning(f"[uploader] Upload attempt {attempt+1} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"[uploader] All upload attempts failed: {e}")
                return ""

    # Thumbnail (non-blocking)
    if thumb_path:
        try:
            set_thumbnail(yt, video_id, thumb_path)
        except Exception as e:
            log.warning(f"[uploader] Thumbnail error (non-fatal): {e}")

    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    log.info(f"[uploader] Story published: {yt_url}")
    return yt_url


def is_configured() -> bool:
    """Return True if YouTube OAuth credentials file exists."""
    return _YT_LIBS_OK and os.path.exists(YOUTUBE_OAUTH_FILE)
