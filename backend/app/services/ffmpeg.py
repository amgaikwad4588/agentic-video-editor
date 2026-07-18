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

def _escape_path(path: str) -> str:
    """Escape a filesystem path for a quoted filtergraph option value.

    Forward slashes + backslash-escaped drive colon, wrapped in single quotes
    by the caller. ffmpeg 7's rewritten graph parser rejects the bare C\\:
    form that 4.x accepted; the quoted+escaped combination works on both.
    """
    return path.replace("\\", "/").replace(":", "\\:")


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


def _lerp_expr(points: list[tuple[float, float]], tvar: str = "t") -> str:
    """Piecewise-linear ffmpeg expression through (time, value) points.

    Holds the first value before the first point and the last value after the
    last. The result contains commas, so callers must place it inside a
    single-quoted filter option (like enable='...' already does).

    The isnan guard matters: filters evaluate their expressions once at
    configure time with t=NaN, and trunc(NaN) aborts the whole graph - the
    guard returns the first keyframe's value there instead.
    """
    if len(points) == 1:
        return f"{points[0][1]:.6g}"
    expr = f"{points[-1][1]:.6g}"
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:]))):
        seg = (
            f"({v0:.6g}+({v1:.6g}-{v0:.6g})*"
            f"({tvar}-{t0:.4f})/{t1 - t0:.4f})"
        )
        expr = f"if(lt({tvar},{t1:.4f}),{seg},{expr})"
    return (
        f"if(isnan({tvar})+lt({tvar},{points[0][0]:.4f}),"
        f"{points[0][1]:.6g},{expr})"
    )


def _clip_segments(
    clip: Clip, source_duration: float | None
) -> list[tuple[float, float, float]]:
    """Constant-speed (src_start, src_end, speed) pieces of a clip.

    A clip without a ramp is one segment at clip.speed; a speed ramp yields
    one segment per ramp point. Each segment renders as its own trim/setpts
    chain so any speed profile works with plain concat.
    """
    end = clip.end if clip.end is not None else (source_duration or 0.0)
    if not clip.speed_ramp:
        return [(clip.start, end, clip.speed)]
    pts = [p for p in clip.speed_ramp if clip.start + p.at < end]
    segs: list[tuple[float, float, float]] = []
    for j, p in enumerate(pts):
        s = clip.start + p.at
        e = min(end, clip.start + pts[j + 1].at) if j + 1 < len(pts) else end
        if e > s:
            segs.append((s, e, p.speed))
    return segs or [(clip.start, end, clip.speed)]


def _clip_duration(clip: Clip, source_duration: float | None) -> float:
    return sum(
        max(0.0, (e - s) / sp)
        for s, e, sp in _clip_segments(clip, source_duration)
    )


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


def build_export_command(
    timeline: Timeline,
    asset_paths: dict[str, str],
    asset_info: dict[str, MediaInfo],
    output: str | Path,
) -> tuple[list[str], float]:
    """Build the full ffmpeg command for rendering a timeline.

    Returns (argv, expected_output_duration_seconds).
    """
    main_clips = [c for c in timeline.clips if c.track == 0]
    pip_clips = sorted(
        (c for c in timeline.clips if c.track > 0),
        key=lambda c: (c.track, c.offset),
    )
    if not main_clips:
        raise FFmpegError(
            "Timeline is empty - nothing to export"
            if not timeline.clips
            else "No main-track clips - overlay clips need a track-0 base"
        )

    ffmpeg = resolve_ffmpeg()
    font = _escape_path(resolve_font())

    inputs: list[str] = []
    filters: list[str] = []
    concat_refs: list[str] = []
    sidecar_files: list[Path] = []  # drawtext textfile sidecars ({output}.ov*.txt)
    total_duration = 0.0

    seg_idx = 0  # one ffmpeg input per constant-speed segment
    for clip in main_clips:
        src = asset_paths.get(clip.asset_id)
        info = asset_info.get(clip.asset_id)
        if src is None or info is None:
            raise FFmpegError(f"Clip {clip.id}: unknown asset {clip.asset_id}")

        end = clip.end if clip.end is not None else (info.duration or 0.0)
        if end <= clip.start:
            raise FFmpegError(f"Clip {clip.id}: end ({end}) must be after start ({clip.start})")
        segments = _clip_segments(clip, info.duration)
        clip_out_dur = _clip_duration(clip, info.duration)
        total_duration += clip_out_dur

        seg_out_start = 0.0  # segment's start in the clip's OUTPUT time
        for s_idx, (s, e, speed) in enumerate(segments):
            i = seg_idx
            seg_idx += 1
            inputs += ["-i", src]
            seg_out = (e - s) / speed
            first, last = s_idx == 0, s_idx == len(segments) - 1

            # Fades live on the clip; apply in on the first segment, out on
            # the last, clamped to that segment's own output duration.
            fades_v, fades_a = [], []
            if first and clip.fade_in > 0:
                d = min(clip.fade_in, seg_out)
                fades_v.append(f"fade=t=in:st=0:d={d:.4f}")
                fades_a.append(f"afade=t=in:st=0:d={d:.4f}")
            if last and clip.fade_out > 0:
                d = min(clip.fade_out, seg_out)
                st = max(0.0, seg_out - d)
                fades_v.append(f"fade=t=out:st={st:.4f}:d={d:.4f}")
                fades_a.append(f"afade=t=out:st={st:.4f}:d={d:.4f}")

            # ---- video chain: trim -> speed -> normalise -> overlays
            # NOTE: no per-segment fps filter. In ffmpeg 4.x, fps= placed
            # after trim pads the segment back out to the source duration on
            # flush, silently inflating clips (docs/ERRORS-AND-FIXES.md #16).
            # Frame rate is normalised once at the output with -r instead.
            v = (
                f"[{i}:v]trim=start={s}:end={e},"
                f"setpts=(PTS-STARTPTS)/{speed},"
                f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
                f"format=yuv420p"
            )
            if clip.filter in _CLIP_FILTERS:
                v += "," + _CLIP_FILTERS[clip.filter]

            if clip.keyframes:
                # Transform keyframes: rotate/zoom the normalised frame, then
                # composite onto a black canvas at the keyframed position.
                # Times are in clip OUTPUT seconds; segment-local t is offset
                # by the segment's start in the clip so ramped clips animate
                # continuously.
                kfs = clip.keyframes
                tv = f"(t+{seg_out_start:.4f})" if seg_out_start > 0 else "t"
                filters.append(v + f"[kb{i}]")
                k = f"[kb{i}]"
                if any(kf.rotation for kf in kfs):
                    r = _lerp_expr([(kf.at, kf.rotation) for kf in kfs], tv)
                    k += f"rotate=a='({r})*PI/180':fillcolor=black,"
                sc = _lerp_expr([(kf.at, kf.scale) for kf in kfs], tv)
                # trunc(../2)*2 keeps dimensions even for yuv420p.
                k += (
                    f"scale=w='trunc(iw*({sc})/2)*2'"
                    f":h='trunc(ih*({sc})/2)*2':eval=frame[ks{i}]"
                )
                filters.append(k)
                filters.append(
                    f"color=c=black:s={OUT_W}x{OUT_H}:r={OUT_FPS}[bg{i}]"
                )
                x = _lerp_expr([(kf.at, kf.x) for kf in kfs], tv)
                y = _lerp_expr([(kf.at, kf.y) for kf in kfs], tv)
                v = (
                    f"[bg{i}][ks{i}]overlay=x='(W-w)/2+({x})'"
                    f":y='(H-h)/2+({y})':shortest=1,format=yuv420p"
                )

            if fades_v:
                v += "," + ",".join(fades_v)
            for ov in clip.overlays:
                # Overlay windows are in clip output time; intersect with this
                # segment's output span and shift to segment-local time.
                ov_end = ov.end if ov.end is not None else clip_out_dur
                lo = max(0.0, ov.start - seg_out_start)
                hi = min(seg_out, ov_end - seg_out_start)
                if hi <= lo:
                    continue
                # User text goes through textfile= instead of text=: ffmpeg
                # 7's graph parser mis-splits quoted values that mix colons
                # and escaped apostrophes, and a sidecar file sidesteps the
                # whole escaping problem for arbitrary text. The files sit
                # next to the output and are cleaned up by export_timeline.
                txt_path = Path(f"{output}.ov{i}_{len(sidecar_files)}.txt")
                txt_path.write_text(ov.text, encoding="utf-8")
                sidecar_files.append(txt_path)
                v += (
                    f",drawtext=fontfile='{font}'"
                    f":textfile='{_escape_path(str(txt_path))}'"
                    f":fontsize={ov.font_size}:fontcolor={ov.color}"
                    f":x={ov.x}:y={ov.y}"
                    f":enable='between(t,{lo:.4f},{hi:.4f})'"
                    f":box=1:boxcolor=black@0.35:boxborderw=12"
                )
            v += f"[v{i}]"
            filters.append(v)

            # ---- audio chain: real audio or injected silence (gotcha #3)
            if info.has_audio:
                a = (
                    f"[{i}:a]atrim=start={s}:end={e},"
                    f"asetpts=PTS-STARTPTS,{_atempo_chain(speed)},"
                    f"volume={clip.volume}"
                    f"{(',' + ','.join(fades_a)) if fades_a else ''},"
                    f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo[a{i}]"
                )
            else:
                a = (
                    f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE},"
                    f"atrim=duration={seg_out:.4f}[a{i}]"
                )
            filters.append(a)
            concat_refs.append(f"[v{i}][a{i}]")
            seg_out_start += seg_out

    vmain, amain = ("[vmain]", "[amain]") if pip_clips else ("[vout]", "[aout]")
    filters.append(
        f"{''.join(concat_refs)}concat=n={seg_idx}:v=1:a=1{vmain}{amain}"
    )

    # ---- overlay (PiP) tracks: composite over the main programme ---------
    cur_v = vmain
    mix_refs = [amain]
    for k, clip in enumerate(pip_clips):
        src = asset_paths.get(clip.asset_id)
        info = asset_info.get(clip.asset_id)
        if src is None or info is None:
            raise FFmpegError(f"Clip {clip.id}: unknown asset {clip.asset_id}")
        end = clip.end if clip.end is not None else (info.duration or 0.0)
        if end <= clip.start:
            raise FFmpegError(f"Clip {clip.id}: end ({end}) must be after start ({clip.start})")
        out_dur = (end - clip.start) / clip.speed
        off = clip.offset
        i = seg_idx
        seg_idx += 1
        inputs += ["-i", src]

        # PiP video: trim -> speed -> fit inside the canvas WITHOUT padding
        # (pad bars would obscure the main track), alpha format so a rotate
        # can fill transparent. PTS shifted by `offset` so the overlay filter
        # pulls frames at the right main-timeline moment.
        kfs = clip.keyframes
        tv = f"(t-{off:.4f})"
        v = (
            f"[{i}:v]trim=start={clip.start}:end={end},"
            f"setpts=(PTS-STARTPTS)/{clip.speed}+{off:.4f}/TB,"
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"format=yuva420p"
        )
        if clip.filter in _CLIP_FILTERS:
            v += "," + _CLIP_FILTERS[clip.filter]
        if clip.fade_in > 0:
            d = min(clip.fade_in, out_dur)
            v += f",fade=t=in:st={off:.4f}:d={d:.4f}:alpha=1"
        if clip.fade_out > 0:
            d = min(clip.fade_out, out_dur)
            v += f",fade=t=out:st={off + out_dur - d:.4f}:d={d:.4f}:alpha=1"
        if kfs and any(kf.rotation for kf in kfs):
            r = _lerp_expr([(kf.at, kf.rotation) for kf in kfs], tv)
            v += f",rotate=a='({r})*PI/180':fillcolor=none"
        if kfs:
            sc = _lerp_expr([(kf.at, kf.scale) for kf in kfs], tv)
            v += (
                f",scale=w='trunc(iw*({sc})/2)*2'"
                f":h='trunc(ih*({sc})/2)*2':eval=frame"
            )
        v += f"[pv{k}]"
        filters.append(v)

        x = _lerp_expr([(kf.at, kf.x) for kf in kfs], tv) if kfs else "0"
        y = _lerp_expr([(kf.at, kf.y) for kf in kfs], tv) if kfs else "0"
        nxt = "[vout]" if k == len(pip_clips) - 1 else f"[vo{k}]"
        filters.append(
            f"{cur_v}[pv{k}]overlay=x='(W-w)/2+({x})':y='(H-h)/2+({y})'"
            f":enable='between(t,{off:.4f},{off + out_dur:.4f})'{nxt}"
        )
        cur_v = nxt

        if info.has_audio and clip.volume > 0:
            filters.append(
                f"[{i}:a]atrim=start={clip.start}:end={end},"
                f"asetpts=PTS-STARTPTS,{_atempo_chain(clip.speed)},"
                f"volume={clip.volume},"
                f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo,"
                f"adelay={int(off * 1000)}:all=1[pa{k}]"
            )
            mix_refs.append(f"[pa{k}]")

    if pip_clips:
        if len(mix_refs) == 1:
            filters.append(f"{amain}acopy[aout]")
        else:
            filters.append(
                f"{''.join(mix_refs)}amix=inputs={len(mix_refs)}"
                f":duration=first:normalize=0[aout]"
            )

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

    try:
        _run_export(argv, expected, on_progress)
    finally:
        # Overlay textfile sidecars written by build_export_command.
        for txt in Path(output).parent.glob(f"{Path(output).name}.ov*.txt"):
            txt.unlink(missing_ok=True)


def _run_export(
    argv: list[str],
    expected: float,
    on_progress: Callable[[float], None] | None,
) -> None:
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
