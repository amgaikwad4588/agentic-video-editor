"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Group, Layer, Rect, Stage, Text } from "react-konva";

import { api } from "@/lib/api";
import { filterCss } from "@/lib/filters";
import { clipAtTime, formatTime, timelineDuration } from "@/lib/timeline";
import type { MediaAsset, Timeline } from "@/lib/types";

// Must match backend OUT_W/OUT_H so overlay positions preview accurately.
const EXPORT_W = 1280;
const EXPORT_H = 720;

/** Evaluate the small subset of drawtext position expressions we generate. */
function overlayXY(
  x: string, y: string, fontSize: number, textLen: number, scale: number,
): { px: number; py: number } {
  const approxTextW = textLen * fontSize * 0.55;
  const evalExpr = (expr: string, total: number, size: number): number => {
    if (expr === "(w-text_w)/2") return (EXPORT_W - approxTextW) / 2;
    if (expr === "(h-text_h)/2") return (EXPORT_H - fontSize) / 2;
    if (expr === "h-th-40") return EXPORT_H - fontSize - 40;
    const n = Number(expr);
    return Number.isFinite(n) ? n : total / 2 - size / 2;
  };
  return {
    px: evalExpr(x, EXPORT_W, approxTextW) * scale,
    py: evalExpr(y, EXPORT_H, fontSize) * scale,
  };
}

export default function PreviewPlayerInner({
  timeline,
  assets,
  selectedClipId,
}: {
  timeline: Timeline;
  assets: Map<string, MediaAsset>;
  selectedClipId: string | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [size, setSize] = useState({ w: 640, h: 360 });

  const total = useMemo(() => timelineDuration(timeline, assets), [timeline, assets]);
  const pos = useMemo(
    () => clipAtTime(timeline, assets, Math.min(playhead, Math.max(0, total - 0.01))),
    [timeline, assets, playhead, total],
  );

  // Track container size for responsive canvas.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      setSize({ w, h: (w * 9) / 16 });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Keep the <video> element in sync with the playhead's clip/source time.
  const currentAssetId = pos?.clip.asset_id ?? null;
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !pos) return;
    const targetSrc = api.mediaFileUrl(pos.clip.asset_id);
    if (!video.src.endsWith(targetSrc)) {
      video.src = targetSrc;
    }
    if (Math.abs(video.currentTime - pos.sourceTime) > 0.25) {
      video.currentTime = pos.sourceTime;
    }
    video.playbackRate = pos.clip.speed;
    video.volume = Math.min(1, pos.clip.volume);
    if (playing) video.play().catch(() => setPlaying(false));
    else video.pause();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentAssetId, playing]);

  // Advance the playhead while playing (drives clip transitions).
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setPlayhead((t) => {
        const next = t + dt;
        if (next >= total) {
          setPlaying(false);
          return 0;
        }
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, total]);

  const seek = useCallback((t: number) => {
    setPlayhead(Math.max(0, Math.min(t, total)));
    const video = videoRef.current;
    if (video && pos) video.currentTime = pos.sourceTime;
  }, [total, pos]);

  const scale = size.w / EXPORT_W;
  const visibleOverlays = (pos?.clip.overlays ?? []).filter((o) => {
    const t = pos?.offsetInClip ?? 0;
    return t >= o.start && (o.end == null || t <= o.end);
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
      <div
        ref={containerRef}
        style={{
          position: "relative",
          background: "#1A1A1A",
          overflow: "hidden",
          boxShadow: "0 8px 32px rgba(0,0,0,0.12), inset 0 0 0 1px rgba(0,0,0,0.06)",
        }}
      >
        <video
          ref={videoRef}
          width={size.w}
          height={size.h}
          style={{
            display: "block",
            width: "100%",
            aspectRatio: "16/9",
            objectFit: "contain",
            // Mirror the clip's colour treatment so the preview matches export.
            filter: filterCss(pos?.clip.filter),
          }}
          muted={pos?.clip.volume === 0}
        />
        {/* Konva layer mirrors what drawtext will burn in at export */}
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          <Stage width={size.w} height={size.h}>
            <Layer>
              {visibleOverlays.map((o, i) => {
                const { px, py } = overlayXY(o.x, o.y, o.font_size, o.text.length, scale);
                const fs = o.font_size * scale;
                return (
                  <Group key={i}>
                    <Rect
                      x={px - 8}
                      y={py - 4}
                      width={o.text.length * fs * 0.55 + 16}
                      height={fs + 8}
                      fill="black"
                      opacity={0.35}
                      cornerRadius={4}
                    />
                    <Text
                      x={px}
                      y={py}
                      text={o.text}
                      fontSize={fs}
                      fill={o.color.startsWith("0x") ? `#${o.color.slice(2)}` : o.color}
                      fontFamily="Arial"
                    />
                  </Group>
                );
              })}
              {!pos && (
                <Text
                  x={16}
                  y={size.h / 2 - 10}
                  text="An empty timeline. Add a piece from the archive."
                  fontSize={16}
                  fontStyle="italic"
                  fontFamily="Georgia"
                  fill="#EBE5DE"
                />
              )}
            </Layer>
          </Stage>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="transport" onClick={() => setPlaying((p) => !p)} disabled={!pos}>
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(total, 0.01)}
          step={0.05}
          value={playhead}
          onChange={(e) => seek(Number(e.target.value))}
          style={{ flex: 1 }}
        />
        <span className="muted" style={{ minWidth: 110, textAlign: "right" }}>
          {formatTime(playhead)} / {formatTime(total)}
        </span>
        <button
          title="Maximize the preview (Esc to exit)"
          aria-label="Maximize preview"
          style={{ minHeight: 34, padding: "0 12px" }}
          onClick={() => {
            const el = containerRef.current;
            if (!el) return;
            if (document.fullscreenElement) document.exitFullscreen();
            else el.requestFullscreen().catch(() => {});
          }}
        >
          ⛶
        </button>
      </div>
      {selectedClipId && pos?.clip.id === selectedClipId && (
        <div className="muted" style={{ fontSize: 12 }}>Previewing selected clip</div>
      )}
    </div>
  );
}
