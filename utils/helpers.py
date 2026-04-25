"""
MagicLight v2.0 — Helpers
ID generation, slug creation, file naming utilities.
"""

import re
import unicodedata
from datetime import datetime
from utils.config import ID_FORMAT, SLUG_MAX_LEN


# ─── ID Generation ────────────────────────────────────────────────────────────

def generate_id(dt: datetime | None = None) -> str:
    """
    Generate a unique job ID in format YYYYMMDDHHMMSS.
    Example: 20260425143055
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(ID_FORMAT)


# ─── Slug Helpers ─────────────────────────────────────────────────────────────

def make_slug(title: str, max_len: int = SLUG_MAX_LEN) -> str:
    """
    Convert a title to a URL-safe slug:
      - Remove emojis and non-ASCII characters
      - Lowercase
      - Replace spaces and underscores with hyphens
      - Remove all non-alphanumeric characters except hyphens
      - Trim to max_len characters
      - Strip leading/trailing hyphens

    Example: "My Kids Story! 😊" → "my-kids-story"
    """
    # Normalise unicode (decompose accented chars)
    title = unicodedata.normalize("NFKD", title)

    # Remove non-ASCII (removes emojis, special unicode)
    title = title.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    title = title.lower()

    # Replace spaces/underscores with hyphen
    title = re.sub(r"[\s_]+", "-", title)

    # Remove anything not alphanumeric or hyphen
    title = re.sub(r"[^a-z0-9\-]", "", title)

    # Collapse multiple hyphens
    title = re.sub(r"-{2,}", "-", title)

    # Trim to max length and clean edges
    title = title[:max_len].strip("-")

    return title or "untitled"


# ─── File Naming ──────────────────────────────────────────────────────────────

def build_filename(job_id: str, title: str, ext: str = "mp4") -> str:
    """
    Build standard filename: {ID}_{slug}.{ext}
    Example: 20260425143055_my-kids-story.mp4
    """
    slug = make_slug(title)
    return f"{job_id}_{slug}.{ext}"


def build_raw_path(job_id: str, title: str) -> str:
    """Return relative path string for a raw video file."""
    from utils.config import OUTPUT_RAW
    return str(OUTPUT_RAW / build_filename(job_id, title, "mp4"))


def build_processed_path(job_id: str, title: str) -> str:
    """Return relative path string for a processed video file."""
    from utils.config import OUTPUT_PROCESSED
    return str(OUTPUT_PROCESSED / build_filename(job_id, title, "mp4"))


def build_thumbnail_path(job_id: str, title: str) -> str:
    """Return relative path string for a thumbnail file."""
    from utils.config import OUTPUT_THUMBNAILS
    return str(OUTPUT_THUMBNAILS / build_filename(job_id, title, "jpg"))


# ─── Misc ─────────────────────────────────────────────────────────────────────

def now_str() -> str:
    """Return current datetime as ISO string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_str(val) -> str:
    """Safely convert any value to string, returning empty string for None."""
    return str(val) if val is not None else ""
