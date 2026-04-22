"""
processor.py — MagicLight Auto v3.0
=====================================
FFmpeg video processing module.
Input:  temp/downloads/<safe_name>.mp4
Output: temp/processed/<safe_name>_Processed.mp4

Extracted from main.py lines 2050–2466.
"""

import os
import re
import subprocess
from pathlib import Path
from datetime import datetime

from config import (
    OUT_BASE, VIDEO_EXTS, LOCAL_OUTPUT_ENABLED,
    LOGO_PATH, ENDSCREEN_VIDEO, TRIM_SECONDS,
    LOGO_X, LOGO_Y, LOGO_WIDTH, LOGO_OPACITY,
    ENDSCREEN_ENABLED, PROCESSED_DIR, log, DEBUG
)

# ── Rich console (optional) ───────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.progress import (Progress, SpinnerColumn, TextColumn,
                               BarColumn, TimeElapsedColumn)
    _has_rich = True
    console = Console(highlight=False, emoji=False)
except ImportError:
    _has_rich = False
    class _FallbackConsole:
        def print(self, *a, **kw): print(*a)
        def rule(self, *a, **kw): print("─" * 40)
    console = _FallbackConsole()

# ── FFmpeg encode profiles ────────────────────────────────────────────────────
PROFILES = {
    "720p": {
        "label": "720p — Fast Encode",
        "resolution": "1280x720", "crf": 23,
        "preset": "fast", "audio_br": "128k",
    },
    "1080p": {
        "label": "1080p — Standard",
        "resolution": "1920x1080", "crf": 23,
        "preset": "veryfast", "audio_br": "128k",
    },
    "1080p_hq": {
        "label": "1080p HQ — Best Quality (Slow)",
        "resolution": "1920x1080", "crf": 18,
        "preset": "slow", "audio_br": "192k",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def has_valid_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=10
        )
        return float(result.stdout.strip()) > 0
    except Exception:
        return False


def has_audio_stream(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def scan_videos(base: Path) -> list[Path]:
    if not base or not base.exists():
        return []
    return sorted(
        p for p in base.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.endswith("_processed")
        and "-Processed-" not in p.stem
        and "_thumb" not in p.stem
    )


def _make_safe(row_num, title, file_type=""):
    safe_title = re.sub(r"[^\w\-]", "_", str(title)[:30])
    if file_type:
        return f"R{row_num}_{safe_title}_{file_type}".strip("_")
    return re.sub(r"[^\w\-]", "_", f"R{row_num}_{safe_title}").strip("_")


def extract_row_num(stem: str) -> int | None:
    m = re.match(r"R(\d+)_", stem)
    if m:
        return int(m.group(1))
    m = re.match(r"row(\d+)[_\-]", stem, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


# ── FFmpeg command builder ────────────────────────────────────────────────────
def build_ffmpeg_cmd(
    input_file: Path, output_file: Path,
    trim_seconds: int, logo_path: Path,
    logo_x: int, logo_y: int, logo_width: int, logo_opacity: float,
    endscreen_enabled: bool, endscreen_path, profile_key: str = "1080p"
) -> list[str]:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    if not has_valid_video(input_file):
        raise ValueError(f"Invalid video file: {input_file}")
    if trim_seconds < 0:
        raise ValueError(f"trim_seconds must be non-negative, got {trim_seconds}")

    profile = PROFILES.get(profile_key, PROFILES["1080p"])
    res = profile["resolution"]
    w, h = res.split("x")
    scale = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    crf    = profile["crf"]
    preset = profile["preset"]
    ab     = profile["audio_br"]

    dur = get_duration(input_file)
    if dur <= 0:
        raise ValueError(f"Cannot determine video duration: {input_file}")

    if trim_seconds >= dur:
        log.warning(f"trim_seconds ({trim_seconds}) >= video duration ({dur:.1f}s), using full video")
        trim_dur = dur
    else:
        trim_dur = dur - trim_seconds

    if trim_dur <= 0.1:
        raise ValueError(f"Resulting video duration too short: {trim_dur:.1f}s")

    input_has_audio = has_audio_stream(input_file)
    has_logo      = logo_path.exists() and logo_width > 0
    has_endscreen = (endscreen_enabled and endscreen_path and
                     Path(endscreen_path).exists() and has_valid_video(Path(endscreen_path)))

    inputs = ["-i", str(input_file)]
    logo_idx = end_idx = None
    if has_logo:
        logo_idx = len(inputs) // 2
        inputs += ["-i", str(logo_path)]
    if has_endscreen:
        end_idx = len(inputs) // 2
        inputs += ["-i", str(endscreen_path)]

    filters = []
    filters.append(f"[0:v]trim=duration={trim_dur:.3f},setpts=PTS-STARTPTS,{scale}[base]")
    if input_has_audio:
        filters.append(f"[0:a]atrim=duration={trim_dur:.3f},asetpts=PTS-STARTPTS[main_a]")

    if has_logo:
        logo_scale = f"[{logo_idx}:v]scale={logo_width}:-1[logo_s]"
        if logo_opacity < 1.0:
            logo_scale += f";[logo_s]format=rgba,colorchannelmixer=aa={logo_opacity:.2f}[logo_f]"
            lref = "logo_f"
        else:
            lref = "logo_s"
        filters.append(logo_scale)
        filters.append(f"[base][{lref}]overlay={logo_x}:{logo_y}[vid_logo]")
        main_v = "vid_logo"
    else:
        main_v = "base"

    map_v = map_a = None
    if has_endscreen:
        end_dur = get_duration(Path(endscreen_path))
        if end_dur <= 0:
            raise ValueError(f"Invalid endscreen duration: {end_dur}")
        cross = max(0.1, min(0.5, trim_dur * 0.04, end_dur * 0.3, trim_dur * 0.25))
        if cross >= trim_dur:
            log.warning("Crossfade too long — disabling endscreen")
            has_endscreen = False
        else:
            xfade_off = max(0, trim_dur - cross)
            filters.append(f"[{end_idx}:v]trim=duration={end_dur:.3f},setpts=PTS-STARTPTS,{scale}[end_v]")
            if input_has_audio:
                filters.append(f"[{end_idx}:a]atrim=duration={end_dur:.3f},asetpts=PTS-STARTPTS[end_a]")
                filters.append(f"[{main_v}][end_v]xfade=transition=fade:duration={cross:.3f}:offset={xfade_off:.3f}[final_v]")
                filters.append(f"[main_a][end_a]acrossfade=d={cross:.3f}[final_a]")
                map_v, map_a = "[final_v]", "[final_a]"
            else:
                filters.append(f"[{main_v}][end_v]xfade=transition=fade:duration={cross:.3f}:offset={xfade_off:.3f}[final_v]")
                map_v, map_a = "[final_v]", None

    if not has_endscreen:
        map_v = f"[{main_v}]"
        map_a = "[main_a]" if input_has_audio else None

    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", map_v])
    if map_a:
        cmd += ["-map", map_a, "-c:a", "aac", "-b:a", ab]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_file)]
    return cmd


# ── FFmpeg runner ─────────────────────────────────────────────────────────────
def run_ffmpeg(cmd: list[str], input_file: Path, output_file: Path,
               dry_run: bool = False) -> bool:
    if dry_run:
        log.info(f"[DRY-RUN] {' '.join(cmd[:6])} …")
        return True

    duration = get_duration(input_file)
    proc = None
    stdout_lines = []

    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, universal_newlines=True, bufsize=1) as proc:
            if _has_rich:
                with Progress(SpinnerColumn(),
                              TextColumn("[progress.description]{task.description}"),
                              BarColumn(),
                              TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                              TimeElapsedColumn(), console=console) as progress:
                    task = progress.add_task(f"[cyan]Encoding {input_file.name}", total=100)
                    for line in proc.stdout:
                        stdout_lines.append(line.strip())
                        if "time=" in line:
                            try:
                                tp = line.split("time=")[1].split()[0]
                                h, m, s = tp.split(":")
                                cur = int(h) * 3600 + int(m) * 60 + float(s)
                                if duration > 0:
                                    progress.update(task, completed=min(100, int(cur / duration * 100)))
                            except Exception:
                                pass
            else:
                for line in proc.stdout:
                    stdout_lines.append(line.strip())
                    if "time=" in line:
                        print(f"  {line.strip()}")
            rc = proc.wait()

        if rc == 0:
            log.info(f"[ffmpeg] Encoded -> {output_file.name}")
            return True
        else:
            log.error(f"[ffmpeg] Exited with code {rc}")
            for line in stdout_lines[-5:]:
                log.warning(f"  {line}")
            return False
    except Exception as e:
        log.error(f"[ffmpeg] Fatal error: {e}")
        if proc:
            try:
                proc.kill(); proc.wait()
            except Exception:
                pass
        return False


# ── Main entry point ──────────────────────────────────────────────────────────
def process_video(input_video: Path, dry_run: bool = False,
                  output_dir: Path | None = None) -> tuple[bool, Path | None]:
    """
    Process a single video with FFmpeg.

    Returns (success, output_path).
    output_path is None on failure.
    """
    if not LOCAL_OUTPUT_ENABLED:
        log.warning("[process] Local output disabled — skipping")
        return False, None

    if not check_ffmpeg():
        log.error("[process] FFmpeg not found. Install FFmpeg and add to PATH.")
        return False, None

    if not input_video.exists():
        log.error(f"[process] Input not found: {input_video}")
        return False, None

    if not has_valid_video(input_video):
        log.error(f"[process] Invalid video file: {input_video}")
        return False, None

    if input_video.stat().st_size < 100_000:  # < 100 KB
        log.warning(f"[process] Video too small: {input_video}")
        return False, None

    stem    = input_video.stem
    row_num = extract_row_num(stem)

    if "-Generated-" in stem:
        title_part = stem.split("-Generated-", 1)[1]
    elif "_" in stem:
        title_part = stem.split("_", 1)[1]
    else:
        title_part = stem

    # Determine output path
    dest_dir = output_dir or PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    if row_num:
        safe_name   = _make_safe(row_num, title_part.replace("_", " "), "Processed")
        output_file = dest_dir / f"{safe_name}{input_video.suffix}"
    else:
        output_file = dest_dir / f"{input_video.stem}_processed{input_video.suffix}"

    if output_file.exists():
        log.info(f"[process] Already processed — skipping ({output_file.name})")
        return True, output_file

    # Validate endscreen
    endscreen_enabled = ENDSCREEN_ENABLED
    endscreen_path    = ENDSCREEN_VIDEO
    if ENDSCREEN_ENABLED:
        if not ENDSCREEN_VIDEO.exists() or not has_valid_video(ENDSCREEN_VIDEO):
            log.warning("[process] Endscreen invalid — disabled for this run")
            endscreen_enabled = False
            endscreen_path    = None

    if not LOGO_PATH.exists():
        log.warning(f"[process] Logo not found: {LOGO_PATH}")

    try:
        cmd = build_ffmpeg_cmd(
            input_file=input_video, output_file=output_file,
            trim_seconds=TRIM_SECONDS,
            logo_path=LOGO_PATH, logo_x=LOGO_X, logo_y=LOGO_Y,
            logo_width=LOGO_WIDTH, logo_opacity=LOGO_OPACITY,
            endscreen_enabled=endscreen_enabled, endscreen_path=endscreen_path,
        )
        log.info(f"[process] Processing -> {output_file.name}")
        success = run_ffmpeg(cmd, input_video, output_file, dry_run=dry_run)

        if success and not dry_run:
            if not output_file.exists():
                log.error(f"[process] Output not created: {output_file}")
                return False, None
            if not has_valid_video(output_file):
                log.error(f"[process] Output invalid: {output_file}")
                try:
                    output_file.unlink()
                except Exception:
                    pass
                return False, None
            size_mb = output_file.stat().st_size / 1_048_576
            log.info(f"[process] Complete: {size_mb:.1f} MB -> {output_file}")
            return True, output_file

        return success, output_file if success else None

    except Exception as e:
        log.error(f"[process] Failed: {e}")
        if output_file.exists():
            try:
                output_file.unlink()
            except Exception:
                pass
        return False, None


def process_all(videos: list[Path] = None, dry_run: bool = False,
                output_dir: Path | None = None) -> int:
    """Batch-process all given videos. Returns 0 on success, 1 if any failed."""
    if videos is None:
        videos = scan_videos(Path(OUT_BASE))
    if not videos:
        log.warning("[process] No unprocessed videos found.")
        return 0

    ok = fail = 0
    for i, vid in enumerate(videos, 1):
        log.info(f"[process] [{i}/{len(videos)}] {vid.name}")
        success, _ = process_video(vid, dry_run=dry_run, output_dir=output_dir)
        if success:
            ok += 1
        else:
            fail += 1

    log.info(f"[process] Done — OK={ok}  FAIL={fail}")
    return 0 if fail == 0 else 1


def cleanup_processed(path: Path) -> bool:
    """Delete a processed file after successful upload."""
    try:
        if path and path.exists():
            path.unlink()
            log.info(f"[process] Cleaned up: {path.name}")
            return True
    except Exception as e:
        log.warning(f"[process] Cleanup failed: {e}")
    return False


def load_process_cfg() -> dict:
    return {
        "magiclight_output": PROCESSED_DIR,
        "logo_path": LOGO_PATH,
        "endscreen_video": ENDSCREEN_VIDEO,
        "trim_seconds": TRIM_SECONDS,
        "logo_x": LOGO_X, "logo_y": LOGO_Y,
        "logo_width": LOGO_WIDTH, "logo_opacity": LOGO_OPACITY,
        "endscreen_enabled": ENDSCREEN_ENABLED,
    }
