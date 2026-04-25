"""
MagicLight v2.0 — FFmpeg Utilities (Process Stage)
Video processing: add logo, endscreen, encode; thumbnail extraction.
"""

import subprocess
from pathlib import Path
from utils.config import BASE_DIR
from utils.logger import get_system_logger

log = get_system_logger("ffmpeg")

LOGO_PATH      = BASE_DIR / "assets" / "logo.png"
ENDSCREEN_PATH = BASE_DIR / "assets" / "endscreen.mp4"


def process_video(
    input_path: str,
    output_path: str,
    job_id: str = "",
    job_log=None,
) -> str:
    """
    Run FFmpeg to produce the final processed video.
    Pipeline: Add logo watermark → concat endscreen → encode H.264/AAC.

    Returns:
        output_path on success.
    Raises:
        RuntimeError on FFmpeg failure.
    """
    _log = job_log or log
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    _log.info(f"[FFmpeg] Processing {Path(input_path).name} → {Path(output_path).name}")

    # Build filter complex: overlay logo (top-right) + concat endscreen
    logo_overlay = ""
    if LOGO_PATH.exists():
        logo_overlay = (
            "[0:v][1:v]overlay=W-w-20:20[v_logo];"
            "[v_logo]"
        )
        inputs  = ["-i", input_path, "-i", str(LOGO_PATH)]
        vfiltro = logo_overlay
    else:
        inputs  = ["-i", input_path]
        vfiltro = "[0:v]"

    # Add endscreen if present
    if ENDSCREEN_PATH.exists():
        inputs += ["-i", str(ENDSCREEN_PATH)]
        filter_complex = (
            f"{vfiltro}setsar=1[vmain];"
            f"[{len(inputs)//2 - 1}:v]setsar=1[vend];"
            "[vmain][0:a][vend]"
            "[0:a]concat=n=2:v=1:a=1[vout][aout]"
        )
        maps = ["-map", "[vout]", "-map", "[aout]"]
    else:
        filter_complex = f"{vfiltro}copy[vout]"
        maps = ["-map", "[vout]", "-map", "0:a?"]

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", filter_complex]
        + maps
        + [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
    )

    _log.debug(f"[FFmpeg] cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (rc={result.returncode}):\n{result.stderr[-2000:]}")

    _log.info(f"[FFmpeg] ✓ Processed → {output_path}")
    return output_path


def extract_thumbnail(
    video_path: str,
    thumb_path: str,
    timestamp: str = "00:00:05",
    job_log=None,
) -> str:
    """
    Extract a single frame from video_path at `timestamp` and save as JPEG.

    Returns:
        thumb_path on success.
    """
    _log = job_log or log
    Path(thumb_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", timestamp,
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        thumb_path,
    ]

    _log.info(f"[FFmpeg] Extracting thumbnail → {thumb_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Thumbnail extraction failed:\n{result.stderr[-1000:]}")

    _log.info(f"[FFmpeg] ✓ Thumbnail saved → {thumb_path}")
    return thumb_path
