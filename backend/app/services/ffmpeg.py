"""FFmpeg integration: binary resolution, probing, thumbnails and export.

Design notes / gotchas this module encodes (see docs/ERRORS-AND-FIXES.md):

1. Binary resolution order: FFMPEG_PATH env -> PATH -> imageio-ffmpeg bundle.
   The bundle ships *only* ffmpeg, not ffprobe, so probing is implemented by
   parsing `ffmpeg -i <file>` stderr instead of calling ffprobe.

2. concat requires all segments to share resolution / pixel format / fps /
   audio layout. Every clip is therefore normalised (scale+pad to the output
   size, fps=30, yuv420p, stereo 44.1kHz) before the concat filter.

3. Sources without an audio stream (screen recordings, testsrc fixtures,
   images) get silent audio injected via anullsrc so concat's a=1 contract
   holds.

4. atempo only accepts factors in [0.5, 2.0]; larger speed changes are
   expressed as a chain of atempo filters.

5. drawtext needs a real font file; there is no portable default, so the
   path is resolved per-OS and can be overridden with FONT_PATH.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import get_settings
from ..models import Clip, Timeline

# Output canvas all clips are normalised to before concat.
OUT_W, OUT_H, OUT_FPS = 1280, 720, 30
AUDIO_RATE = 44100


class FFmpegError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Binary + font resolution
# --------------------------------------------------------------------------

def resolve_ffmpeg() -> str:
    settings = get_settings()
    if settings.ffmpeg_path:
        return settings.ffmpeg_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - env without the package
        raise FFmpegError(
            "ffmpeg not found: install it, set FFMPEG_PATH, "
            "or `pip install imageio-ffmpeg`"
        ) from exc


def resolve_font() -> str:
    settings = get_settings()
    if settings.font_path:
        return settings.font_path
    candidates: list[str]
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates = [rf"{windir}\Fonts\arial.ttf", rf"{windir}\Fonts\segoeui.ttf"]
    elif sys.platform == "darwin":
        candidates = ["/System/Library/Fonts/Helvetica.ttc"]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    raise FFmpegError(
        "No usable font found for drawtext; set FONT_PATH to a .ttf file"
    )


def _run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )


# --------------------------------------------------------------------------
# Probing (ffprobe is not bundled -> parse `ffmpeg -i` stderr)
# --------------------------------------------------------------------------

@dataclass
class MediaInfo:
    duration: float | None
    width: int | None
    height: int | None
    has_audio: bool
    has_video: bool


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #.*Audio:")


def probe(path: str | Path) -> MediaInfo:
    """Extract duration/resolution/streams by parsing ffmpeg's banner output.

    `ffmpeg -i file` exits non-zero ("At least one output file must be
    specified") but still prints full stream info on stderr - that is the
    expected, documented behaviour we rely on here.
    """
    proc = _run([resolve_ffmpeg(), "-hide_banner", "-i", str(path)], timeout=60)
    err = proc.stderr
    if "Invalid data found" in err or "No such file" in err:
        raise FFmpegError(f"Cannot probe {path}: {err.strip().splitlines()[-1]}")

    duration = None
    if m := _DURATION_RE.search(err):
        h, mnt, s = m.groups()
        duration = int(h) * 3600 + int(mnt) * 60 + float(s)

    width = height = None
    if m := _VIDEO_RE.search(err):
        width, height = int(m.group(1)), int(m.group(2))

    return MediaInfo(
        duration=duration,
        width=width,
        height=height,
        has_audio=bool(_AUDIO_RE.search(err)),
        has_video=width is not None,
    )


def make_thumbnail(src: str | Path, dest: str | Path, at: float = 0.5) -> None:
    proc = _run([
        resolve_ffmpeg(), "-y", "-ss", f"{at:.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={OUT_W // 4}:-2", str(dest),
    ], timeout=120)
    if proc.returncode != 0:
        raise FFmpegError(f"Thumbnail failed: {proc.stderr[-500:]}")


# --------------------------------------------------------------------------
# Filter graph construction
# --------------------------------------------------------------------------

def _escape_drawtext(text: str) -> str:
    """Escape user text for a single-quoted drawtext value.

    Inside single quotes the filtergraph parser treats everything literally
    EXCEPT the quote itself, which must be written as '\\'' (close quote,
    escaped quote, reopen). Combined with expansion=none on the filter, this
    makes arbitrary user text safe - "Let's go: 100%" included. Getting this
    wrong shifts every later quoted region and breaks the whole graph (see
    docs/ERRORS-AND-FIXES.md #6).
    """
    return text.replace("'", "'\\''")


def _atempo_chain(speed: float) -> str:
    """Express any speed in atempo's supported [0.5, 2.0] range as a chain."""
    if 0.5 <= speed <= 2.0:
        return f"atempo={speed:.4f}"
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def _clip_duration(clip: Clip, source_duration: float | None) -> float:
    end = clip.end if clip.end is not None else (source_duration or 0.0)
    return max(0.0, (end - clip.start) / clip.speed)


# Colour treatments selectable per clip (Clip.filter). Grayscale drops
# saturation; sepia is the standard luma-weighted colour mix. The preset pack
# below mirrors the look names in frontend/lib/filters.ts (CSS approximations)
# - keep both sides in sync when adding a look.
_CLIP_FILTERS = {
    "grayscale": "hue=s=0",
    "sepia": (
        "colorchannelmixer="
        ".393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0"
    ),
    "vivid": "eq=saturation=1.45:contrast=1.08",
    "warm": "colorbalance=rs=.13:gs=.02:bs=-.13,eq=saturation=1.1",
    "cool": "colorbalance=rs=-.12:bs=.12,eq=saturation=1.05",
    "vintage": "curves=preset=vintage,vignette=PI/5",
    "matte": "curves=all='0/0.06 0.5/0.5 1/0.94',eq=saturation=0.85",
    "noir": "hue=s=0,eq=contrast=1.35:brightness=0.02",
}


def _fade_filters(clip: Clip, out_dur: float, audio: bool) -> str:
    """fade/afade steps for a clip, positioned in output (post-speed) time.
    Returns '' or a leading-comma filter fragment."""
    name = "afade" if audio else "fade"
    steps = []
    if clip.fade_in > 0:
        steps.append(f"{name}=t=in:st=0:d={min(clip.fade_in, out_dur):.4f}")
    if clip.fade_out > 0:
        d = min(clip.fade_out, out_dur)
        steps.append(f"{name}=t=out:st={max(0.0, out_dur - d):.4f}:d={d:.4f}")
    return ("," + ",".join(steps)) if steps else ""


def build_export_command(
    timeline: Timeline,
    asset_paths: dict[str, str],
    asset_info: dict[str, MediaInfo],
    output: str | Path,
) -> tuple[list[str], float]:
    """Build the full ffmpeg command for rendering a timeline.

    Returns (argv, expected_output_duration_seconds).
    """
    if not timeline.clips:
        raise FFmpegError("Timeline is empty - nothing to export")

    ffmpeg = resolve_ffmpeg()
    font = resolve_font().replace("\\", "/")
    # drawtext on Windows: 'C\:/...' - the drive colon must be escaped inside
    # the filter, else it is parsed as an option separator.
    font = font.replace(":", "\\:")

    inputs: list[str] = []
    filters: list[str] = []
    concat_refs: list[str] = []
    total_duration = 0.0

    for i, clip in enumerate(timeline.clips):
        src = asset_paths.get(clip.asset_id)
        info = asset_info.get(clip.asset_id)
        if src is None or info is None:
            raise FFmpegError(f"Clip {clip.id}: unknown asset {clip.asset_id}")

        inputs += ["-i", src]
        end = clip.end if clip.end is not None else (info.duration or 0.0)
        if end <= clip.start:
            raise FFmpegError(f"Clip {clip.id}: end ({end}) must be after start ({clip.start})")
        out_dur = _clip_duration(clip, info.duration)
        total_duration += out_dur

        # ---- video chain: trim -> speed -> normalise -> overlays
        # NOTE: no per-clip fps filter. In ffmpeg 4.x, fps= placed after trim
        # pads the segment back out to the source duration on flush, silently
        # inflating clips (docs/ERRORS-AND-FIXES.md #16). Frame rate is
        # normalised once at the output with -r instead; concat only needs
        # matching resolution + pixel format.
        v = (
            f"[{i}:v]trim=start={clip.start}:end={end},"
            f"setpts=(PTS-STARTPTS)/{clip.speed},"
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
            f"format=yuv420p"
        )
        if clip.filter in _CLIP_FILTERS:
            v += "," + _CLIP_FILTERS[clip.filter]
        v += _fade_filters(clip, out_dur, audio=False)
        for ov in clip.overlays:
            ov_end = ov.end if ov.end is not None else out_dur
            # fontfile is deliberately NOT quoted (paths have no spaces; the
            # drive colon is already backslash-escaped). expansion=none makes
            # drawtext render the text literally (no %{...} processing).
            v += (
                f",drawtext=fontfile={font}:text='{_escape_drawtext(ov.text)}'"
                f":expansion=none"
                f":fontsize={ov.font_size}:fontcolor={ov.color}"
                f":x={ov.x}:y={ov.y}"
                f":enable='between(t,{ov.start},{ov_end})'"
                f":box=1:boxcolor=black@0.35:boxborderw=12"
            )
        v += f"[v{i}]"
        filters.append(v)

        # ---- audio chain: real audio or injected silence (gotcha #3)
        if info.has_audio:
            a = (
                f"[{i}:a]atrim=start={clip.start}:end={end},"
                f"asetpts=PTS-STARTPTS,{_atempo_chain(clip.speed)},"
                f"volume={clip.volume}"
                f"{_fade_filters(clip, out_dur, audio=True)},"
                f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo[a{i}]"
            )
        else:
            a = (
                f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE},"
                f"atrim=duration={out_dur:.4f}[a{i}]"
            )
        filters.append(a)
        concat_refs.append(f"[v{i}][a{i}]")

    n = len(timeline.clips)
    filters.append(f"{''.join(concat_refs)}concat=n={n}:v=1:a=1[vout][aout]")

    argv = [
        ffmpeg, "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-r", str(OUT_FPS),
        # veryfast over medium: 3-5x faster encodes for a small size penalty.
        # On low-CPU hosts (free-tier containers) medium sits at 0% long
        # enough that users assume the export is broken.
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(output),
    ]
    return argv, total_duration


def export_timeline(
    timeline: Timeline,
    asset_paths: dict[str, str],
    asset_info: dict[str, MediaInfo],
    output: str | Path,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Render the timeline to `output`, reporting progress in [0, 1].

    Deadlock warning (hit for real - docs/ERRORS-AND-FIXES.md #15): reading
    only the stdout progress pipe while stderr is also a pipe lets ffmpeg
    block once the stderr buffer fills, freezing both processes forever.
    stderr therefore goes to a temp file we read after exit.
    """
    argv, expected = build_export_command(timeline, asset_paths, asset_info, output)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errfile:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=errfile,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        # -progress pipe:1 emits key=value lines; out_time_us tracks encoded time.
        for line in proc.stdout:
            if on_progress and expected > 0 and line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(0.99, (us / 1_000_000) / expected))
                except ValueError:
                    pass
        proc.wait(timeout=1800)
        if proc.returncode != 0:
            errfile.seek(0)
            stderr = errfile.read()
            raise FFmpegError(f"Export failed (exit {proc.returncode}): {stderr[-1000:]}")
    if on_progress:
        on_progress(1.0)


def generate_test_clip(dest: str | Path, seconds: float = 2.0, with_audio: bool = True) -> None:
    """Create a small synthetic clip (testsrc + sine). Used by tests/demo seeding."""
    args = [
        resolve_ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=640x360:rate=30",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        args += ["-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    proc = _run(args, timeout=120)
    if proc.returncode != 0:
        raise FFmpegError(f"test clip generation failed: {proc.stderr[-500:]}")
