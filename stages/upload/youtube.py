"""
MagicLight v2.0 — YouTube Uploader (Upload Stage)
Handles OAuth2 authentication and video upload to YouTube Data API v3.
"""

import os
import json
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from utils.config import YOUTUBE_OAUTH_FILE, YOUTUBE_TOKEN_FILE
from utils.logger import get_system_logger

log = get_system_logger("youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_youtube_service():
    creds = None

    if YOUTUBE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(YOUTUBE_OAUTH_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        # Save refreshed token
        YOUTUBE_TOKEN_FILE.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(
    video_path: str,
    thumb_path: str,
    title: str,
    description: str,
    tags: str,
    privacy: str = "public",
    category_id: str = "22",          # "People & Blogs"
    job_log=None,
) -> str:
    """
    Upload a video to YouTube.

    Args:
        video_path: Local path to processed .mp4
        thumb_path: Local path to .jpg thumbnail
        title:      YouTube video title
        description: Video description / summary
        tags:       Comma-separated tags string
        privacy:    "public" | "unlisted" | "private"
        category_id: YouTube category ID

    Returns:
        YouTube watch URL (https://youtu.be/{video_id})
    """
    _log = job_log or log
    _log.info(f"[YouTube] Uploading '{title}'")

    youtube = _get_youtube_service()

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        tag_list,
            "categoryId":  category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=5 * 1024 * 1024)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            _log.debug(f"[YouTube] Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    _log.info(f"[YouTube] ✓ Uploaded video_id={video_id}")

    # Set thumbnail
    if Path(thumb_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg"),
            ).execute()
            _log.info(f"[YouTube] ✓ Thumbnail set for video_id={video_id}")
        except Exception as e:
            _log.warning(f"[YouTube] Thumbnail upload failed: {e}")

    return f"https://youtu.be/{video_id}"
