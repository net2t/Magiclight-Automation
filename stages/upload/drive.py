"""
MagicLight v2.0 — Google Drive Uploader (Upload Stage)
Uploads processed videos to a specified Drive folder using service account.
"""

from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
from utils.config import DRIVE_SERVICE_FILE
from utils.logger import get_system_logger

log = get_system_logger("drive")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_drive_service():
    creds = Credentials.from_service_account_file(str(DRIVE_SERVICE_FILE), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, folder_name: str) -> str:
    """Return the Drive folder ID for folder_name, creating it if needed."""
    query = (
        f"name='{folder_name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get("files", [])
    if items:
        return items[0]["id"]

    # Create folder
    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_to_drive(
    file_path: str,
    folder_name: str = "MagicLight-Videos",
    job_log=None,
) -> str:
    """
    Upload a file to Google Drive inside `folder_name`.

    Returns:
        Shareable Drive link.
    """
    _log = job_log or log
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found for Drive upload: {file_path}")

    _log.info(f"[Drive] Uploading {path.name} to folder '{folder_name}'")

    service   = _get_drive_service()
    folder_id = _get_or_create_folder(service, folder_name)

    file_meta = {
        "name":    path.name,
        "parents": [folder_id],
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)

    uploaded = service.files().create(
        body=file_meta,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    file_id  = uploaded["id"]
    drive_link = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    # Make publicly viewable
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    _log.info(f"[Drive] ✓ Uploaded → {drive_link}")
    return drive_link
