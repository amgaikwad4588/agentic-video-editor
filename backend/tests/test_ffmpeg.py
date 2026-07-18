"""FFmpeg service tests - run against the real (bundled) ffmpeg binary."""

import pytest

from app.models import Clip, TextOverlay, Timeline
from app.services import ffmpeg as ff


def test_resolve_ffmpeg_finds_binary():
    path = ff.resolve_ffmpeg()
    assert path


def test_probe_video_with_audio(sample_clip):
    info = ff.probe(sample_clip)
    assert info.has_video
    assert info.has_audio
    assert info.width == 640 and info.height == 360
    assert info.duration == pytest.approx(2.0, abs=0.3)


def test_probe_video_without_audio(silent_clip):
    info = ff.probe(silent_clip)
    assert info.has_video
    assert not info.has_audio


def test_probe_rejects_garbage(settings, tmp_path):
    bad = tmp_path / "not_a_video.mp4"
    bad.write_bytes(b"this is not a video at all")
    with pytest.raises(ff.FFmpegError):
        ff.probe(bad)


def test_thumbnail(sample_clip, tmp_path):
    dest = tmp_path / "thumb.jpg"
    ff.make_thumbnail(sample_clip, dest)
    assert dest.stat().st_size > 0


def test_atempo_chain_in_range():
    assert ff._atempo_chain(1.5) == "atempo=1.5000"


def test_atempo_chain_above_range():
    # 5x = 2.0 * 2.0 * 1.25
    assert ff._atempo_chain(5.0) == "atempo=2.0,atempo=2.0,atempo=1.2500"


def test_atempo_chain_below_range():
    # 0.25x = 0.5 * 0.5
    assert ff._atempo_chain(0.25) == "atempo=0.5,atempo=0.5000"


def test_overlay_text_goes_through_sidecar_files(sample_clip, tmp_path):
    # Arbitrary user text (apostrophes, colons, %) is passed via textfile=
    # sidecars, not inline text= (ffmpeg 7 parser quirks); the sidecars are
    # removed after the export.
    info = ff.probe(sample_clip)
    tl = Timeline(clips=[Clip(
        asset_id="a", start=0.0, end=1.0,
        overlays=[TextOverlay(text="Let's go: 100%", start=0.0, end=None)],
    )])
    out = tmp_path / "txt.mp4"
    argv, _ = ff.build_export_command(tl, {"a": str(sample_clip)}, {"a": info}, out)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "textfile=" in graph and "text='" not in graph
    sidecars = list(tmp_path.glob("txt.mp4.ov*.txt"))
    assert len(sidecars) == 1
    assert sidecars[0].read_text(encoding="utf-8") == "Let's go: 100%"
    ff.export_timeline(tl, {"a": str(sample_clip)}, {"a": info}, out)
    assert out.stat().st_size > 0
    assert list(tmp_path.glob("txt.mp4.ov*.txt")) == []  # cleaned up


def test_build_export_command_empty_timeline_fails():
    with pytest.raises(ff.FFmpegError, match="empty"):
        ff.build_export_command(Timeline(), {}, {}, "out.mp4")


def test_build_export_command_unknown_asset_fails():
    tl = Timeline(clips=[Clip(asset_id="ghost")])
    with pytest.raises(ff.FFmpegError, match="unknown asset"):
        ff.build_export_command(tl, {}, {}, "out.mp4")


def test_build_export_command_includes_fades_and_filter(sample_clip):
    info = ff.probe(sample_clip)
    tl = Timeline(clips=[
        Clip(asset_id="a", start=0.0, end=2.0, fade_in=0.5, fade_out=0.5,
             filter="grayscale"),
    ])
    argv, _ = ff.build_export_command(tl, {"a": str(sample_clip)}, {"a": info}, "out.mp4")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "hue=s=0" in graph
    assert "fade=t=in:st=0:d=0.5000" in graph
    assert "fade=t=out:st=1.5000:d=0.5000" in graph
    assert "afade=t=in" in graph and "afade=t=out" in graph


def test_export_clip_with_fade_and_filter_renders(sample_clip, tmp_path):
    info = ff.probe(sample_clip)
    tl = Timeline(clips=[
        Clip(asset_id="a", start=0.0, end=1.5, fade_in=0.3, fade_out=0.3,
             filter="sepia"),
    ])
    out = tmp_path / "faded.mp4"
    ff.export_timeline(tl, {"a": str(sample_clip)}, {"a": info}, out)
    assert out.stat().st_size > 0
    assert ff.probe(out).duration == pytest.approx(1.5, abs=0.35)


def test_clip_segments_expand_a_speed_ramp():
    from app.models import SpeedPoint
    clip = Clip(
        asset_id="a", start=1.0, end=7.0,
        speed_ramp=[SpeedPoint(at=0, speed=1.0), SpeedPoint(at=2, speed=2.0)],
    )
    assert ff._clip_segments(clip, None) == [(1.0, 3.0, 1.0), (3.0, 7.0, 2.0)]
    # 2s at 1x + 4s at 2x
    assert ff._clip_duration(clip, None) == pytest.approx(4.0)


def test_export_with_speed_ramp_renders(sample_clip, tmp_path):
    from app.models import SpeedPoint
    info = ff.probe(sample_clip)
    # 0-1s at 1x (1s out) + 1-2s at 2x (0.5s out) => 1.5s output.
    tl = Timeline(clips=[Clip(
        asset_id="a", start=0.0, end=2.0,
        speed_ramp=[SpeedPoint(at=0, speed=1.0), SpeedPoint(at=1, speed=2.0)],
    )])
    out = tmp_path / "ramp.mp4"
    ff.export_timeline(tl, {"a": str(sample_clip)}, {"a": info}, out)
    assert ff.probe(out).duration == pytest.approx(1.5, abs=0.35)


def test_lerp_expr_holds_ends_and_interpolates():
    expr = ff._lerp_expr([(0.0, 1.0), (2.0, 1.5)])
    assert expr.startswith("if(isnan(t)+lt(t,0.0000),1,")
    assert "(1+(1.5-1)*(t-0.0000)/2.0000)" in expr
    # single point degenerates to a constant
    assert ff._lerp_expr([(0.0, 2.0)]) == "2"


def test_export_with_keyframe_zoom_renders(sample_clip, tmp_path):
    from app.models import Keyframe
    info = ff.probe(sample_clip)
    tl = Timeline(clips=[Clip(
        asset_id="a", start=0.0, end=1.5,
        keyframes=[
            Keyframe(at=0.0, scale=1.0, x=0, y=0, rotation=0),
            Keyframe(at=1.5, scale=1.4, x=40, y=-20, rotation=10),
        ],
    )])
    out = tmp_path / "kf.mp4"
    argv, _ = ff.build_export_command(tl, {"a": str(sample_clip)}, {"a": info}, out)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "eval=frame" in graph and "overlay=" in graph and "rotate=" in graph
    ff.export_timeline(tl, {"a": str(sample_clip)}, {"a": info}, out)
    rendered = ff.probe(out)
    assert rendered.duration == pytest.approx(1.5, abs=0.35)
    assert (rendered.width, rendered.height) == (1280, 720)


def test_every_filter_preset_has_a_chain():
    # Every selectable look except "none" must map to an ffmpeg chain.
    from app.models import CLIP_FILTERS
    assert set(CLIP_FILTERS) - {"none"} == set(ff._CLIP_FILTERS)


@pytest.mark.parametrize("look", ["vivid", "warm", "vintage", "matte", "noir"])
def test_export_with_preset_look_renders(sample_clip, tmp_path, look):
    # Real render per preset: proves ffmpeg accepts each chain's syntax
    # (curves/vignette/colorbalance quoting is easy to get subtly wrong).
    info = ff.probe(sample_clip)
    tl = Timeline(clips=[Clip(asset_id="a", start=0.0, end=1.0, filter=look)])
    out = tmp_path / f"{look}.mp4"
    ff.export_timeline(tl, {"a": str(sample_clip)}, {"a": info}, out)
    assert out.stat().st_size > 0


def test_export_two_clips_with_overlay_and_silent_source(
    sample_clip, silent_clip, tmp_path
):
    """End-to-end render: trim + speed + text overlay + mixed audio sources."""
    info_a = ff.probe(sample_clip)
    info_b = ff.probe(silent_clip)
    tl = Timeline(clips=[
        Clip(
            asset_id="a", start=0.0, end=1.0, speed=1.0,
            overlays=[TextOverlay(text="Hello: it's a test", start=0.0, end=None)],
        ),
        Clip(asset_id="b", start=0.5, end=1.5, speed=2.0, volume=0.5),
    ])
    out = tmp_path / "export.mp4"
    progress: list[float] = []

    ff.export_timeline(
        tl,
        {"a": str(sample_clip), "b": str(silent_clip)},
        {"a": info_a, "b": info_b},
        out,
        on_progress=progress.append,
    )

    assert out.stat().st_size > 0
    assert progress and progress[-1] == 1.0
    # Expected duration: 1.0s + (1.0s / 2.0 speed) = 1.5s
    rendered = ff.probe(out)
    assert rendered.duration == pytest.approx(1.5, abs=0.35)
    assert rendered.has_audio  # silent source got anullsrc audio injected
