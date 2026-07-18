"use client";

import { useRef, useState } from "react";

import { FILTER_LOOKS, FILTER_NAMES } from "@/lib/filters";
import { clipDuration, formatTime, moveClip } from "@/lib/timeline";
import type { Clip, MediaAsset, Timeline } from "@/lib/types";

const PX_PER_SECOND = 24;
const MIN_CLIP_SECONDS = 0.2;

interface TrimDrag {
  clipId: string;
  side: "start" | "end";
  originX: number;
  origStart: number;
  origEnd: number;
  maxEnd: number;
  speed: number;
}

export default function TimelineStrip({
  timeline,
  assets,
  selectedClipId,
  onSelect,
  onChange,
}: {
  timeline: Timeline;
  assets: Map<string, MediaAsset>;
  selectedClipId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (t: Timeline) => void;
}) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  // Live in/out points while a trim handle is being dragged; committed once
  // on release so we don't save to the server on every mouse move.
  const [draft, setDraft] = useState<{ clipId: string; start: number; end: number } | null>(null);
  const trimRef = useRef<TrimDrag | null>(null);

  const selected = timeline.clips.find((c) => c.id === selectedClipId) ?? null;

  function trimHandleProps(clip: Clip, side: "start" | "end") {
    return {
      onDragStart: (e: React.DragEvent) => e.preventDefault(),
      onPointerDown: (e: React.PointerEvent) => {
        e.stopPropagation();
        e.preventDefault();
        const assetDur = assets.get(clip.asset_id)?.duration ?? null;
        const end = clip.end ?? assetDur;
        if (end == null) return; // source length unknown: nothing to drag against
        trimRef.current = {
          clipId: clip.id,
          side,
          originX: e.clientX,
          origStart: clip.start,
          origEnd: end,
          maxEnd: assetDur ?? Number.POSITIVE_INFINITY,
          speed: clip.speed,
        };
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        setDraft({ clipId: clip.id, start: clip.start, end });
      },
      onPointerMove: (e: React.PointerEvent) => {
        const t = trimRef.current;
        if (!t) return;
        // Clip width is output time (source/speed), so convert px back to
        // source seconds via speed.
        const deltaSec = ((e.clientX - t.originX) / PX_PER_SECOND) * t.speed;
        if (t.side === "start") {
          const start = Math.min(
            Math.max(0, t.origStart + deltaSec),
            t.origEnd - MIN_CLIP_SECONDS,
          );
          setDraft({ clipId: t.clipId, start, end: t.origEnd });
        } else {
          const end = Math.max(
            Math.min(t.maxEnd, t.origEnd + deltaSec),
            t.origStart + MIN_CLIP_SECONDS,
          );
          setDraft({ clipId: t.clipId, start: t.origStart, end });
        }
      },
      onPointerUp: () => {
        const t = trimRef.current;
        trimRef.current = null;
        if (!t || !draft) return;
        const start = Math.round(draft.start * 10) / 10;
        const end = Math.round(draft.end * 10) / 10;
        setDraft(null);
        onChange({
          clips: timeline.clips.map((c) =>
            c.id === t.clipId ? { ...c, start, end } : c,
          ),
        });
      },
      onClick: (e: React.MouseEvent) => e.stopPropagation(),
    };
  }

  function patchSelected(patch: Partial<Clip>) {
    if (!selected) return;
    onChange({
      clips: timeline.clips.map((c) => (c.id === selected.id ? { ...c, ...patch } : c)),
    });
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="overline">
          The Cut
          {timeline.clips.length > 1 && (
            <span style={{ marginLeft: 10, letterSpacing: "0.08em", textTransform: "none" }}>
              (drag clips to reorder, click to edit)
            </span>
          )}
        </span>
        {selected && (
          <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <label>
              Start{" "}
              <input
                style={{ width: 64, padding: "2px 6px" }}
                type="number"
                min={0}
                step={0.1}
                value={selected.start}
                onChange={(e) => patchSelected({ start: Number(e.target.value) })}
              />
            </label>
            <label>
              End{" "}
              <input
                style={{ width: 64, padding: "2px 6px" }}
                type="number"
                min={0}
                step={0.1}
                value={selected.end ?? ""}
                placeholder="auto"
                onChange={(e) =>
                  patchSelected({ end: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </label>
            <label
              title={
                (selected.speed_ramp?.length ?? 0) > 0
                  ? "This clip has a speed ramp; editing the speed here removes it. Ask the assistant to adjust the ramp."
                  : undefined
              }
            >
              Speed{" "}
              <input
                style={{ width: 52, padding: "2px 6px" }}
                type="number"
                min={0.1}
                max={10}
                step={0.1}
                value={selected.speed}
                onChange={(e) =>
                  // Manually setting a constant speed clears any ramp, same
                  // as the agent's set_speed tool.
                  patchSelected({ speed: Number(e.target.value) || 1, speed_ramp: [] })
                }
              />
            </label>
            <label>
              Vol{" "}
              <input
                style={{ width: 52, padding: "2px 6px" }}
                type="number"
                min={0}
                max={5}
                step={0.1}
                value={selected.volume}
                onChange={(e) => patchSelected({ volume: Number(e.target.value) })}
              />
            </label>
            <label>
              Fade in{" "}
              <input
                style={{ width: 52, padding: "2px 6px" }}
                type="number"
                min={0}
                max={30}
                step={0.1}
                value={selected.fade_in ?? 0}
                onChange={(e) => patchSelected({ fade_in: Number(e.target.value) || 0 })}
              />
            </label>
            <label>
              Fade out{" "}
              <input
                style={{ width: 52, padding: "2px 6px" }}
                type="number"
                min={0}
                max={30}
                step={0.1}
                value={selected.fade_out ?? 0}
                onChange={(e) => patchSelected({ fade_out: Number(e.target.value) || 0 })}
              />
            </label>
            <label>
              Look{" "}
              <select
                value={selected.filter ?? "none"}
                onChange={(e) => patchSelected({ filter: e.target.value as Clip["filter"] })}
              >
                {FILTER_NAMES.map((name) => (
                  <option key={name} value={name}>
                    {name === "none" ? "Colour" : FILTER_LOOKS[name].label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="danger"
              onClick={() => {
                onChange({ clips: timeline.clips.filter((c) => c.id !== selected.id) });
                onSelect(null);
              }}
            >
              Delete clip
            </button>
          </div>
        )}
      </div>

      <div className="clip-strip" onClick={() => onSelect(null)}>
        {timeline.clips.map((clip, i) => {
          const asset = assets.get(clip.asset_id);
          const eff = draft?.clipId === clip.id ? draft : null;
          const shown = eff ? { ...clip, start: eff.start, end: eff.end } : clip;
          const dur = clipDuration(shown, assets);
          return (
            <div
              key={clip.id}
              className={`clip-block ${clip.id === selectedClipId ? "selected" : ""}`}
              style={{ width: Math.max(60, dur * PX_PER_SECOND) }}
              draggable={!draft}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(clip.id);
              }}
              onDragStart={() => setDragIndex(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragIndex !== null && dragIndex !== i) {
                  onChange(moveClip(timeline, dragIndex, i));
                }
                setDragIndex(null);
              }}
              title={`${asset?.filename ?? clip.asset_id} (${formatTime(dur)}). Drag edges to trim.`}
            >
              <div className="label">{asset?.filename ?? clip.asset_id}</div>
              <div className="meta">
                {shown.start.toFixed(1)}s → {shown.end != null ? `${shown.end.toFixed(1)}s` : "end"}
              </div>
              <div className="meta">{formatTime(dur)}</div>
              <div className="badges">
                {(clip.speed_ramp?.length ?? 0) > 0 ? (
                  <span title={clip.speed_ramp.map((p) => `${p.at}s→${p.speed}x`).join(", ")}>
                    ⚡ramp{" "}
                  </span>
                ) : (
                  clip.speed !== 1 && <span>⚡{clip.speed}x </span>
                )}
                {clip.volume !== 1 && <span>🔊{clip.volume} </span>}
                {clip.overlays.length > 0 && <span>💬{clip.overlays.length} </span>}
                {(clip.fade_in > 0 || clip.fade_out > 0) && <span>◐fade </span>}
                {(clip.keyframes?.length ?? 0) > 0 && (
                  <span title={`${clip.keyframes.length} transform keyframes`}>✦anim </span>
                )}
                {clip.filter && clip.filter !== "none" && <span>{clip.filter === "grayscale" ? "b/w" : clip.filter}</span>}
              </div>
              <div className="clip-handle left" title="Drag to trim the in-point" {...trimHandleProps(clip, "start")} />
              <div className="clip-handle right" title="Drag to trim the out-point" {...trimHandleProps(clip, "end")} />
            </div>
          );
        })}
        {timeline.clips.length === 0 && (
          <p className="muted" style={{ alignSelf: "center", margin: "auto" }}>
            Add clips with the “+” button in the media library, or ask the agent.
          </p>
        )}
      </div>
    </div>
  );
}
