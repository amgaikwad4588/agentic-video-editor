"use client";

import { useState } from "react";

import { clipDuration, formatTime, moveClip } from "@/lib/timeline";
import type { Clip, MediaAsset, Timeline } from "@/lib/types";

const PX_PER_SECOND = 24;

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

  const selected = timeline.clips.find((c) => c.id === selectedClipId) ?? null;

  function patchSelected(patch: Partial<Clip>) {
    if (!selected) return;
    onChange({
      clips: timeline.clips.map((c) => (c.id === selected.id ? { ...c, ...patch } : c)),
    });
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>Timeline</strong>
        {selected && (
          <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
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
            <label>
              Speed{" "}
              <input
                style={{ width: 52, padding: "2px 6px" }}
                type="number"
                min={0.1}
                max={10}
                step={0.1}
                value={selected.speed}
                onChange={(e) => patchSelected({ speed: Number(e.target.value) || 1 })}
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
          const dur = clipDuration(clip, assets);
          return (
            <div
              key={clip.id}
              className={`clip-block ${clip.id === selectedClipId ? "selected" : ""}`}
              style={{ width: Math.max(60, dur * PX_PER_SECOND) }}
              draggable
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
              title={`${asset?.filename ?? clip.asset_id} (${formatTime(dur)})`}
            >
              <div className="label">{asset?.filename ?? clip.asset_id}</div>
              <div className="meta">
                {clip.start.toFixed(1)}s → {clip.end != null ? `${clip.end.toFixed(1)}s` : "end"}
              </div>
              <div className="meta">{formatTime(dur)}</div>
              <div className="badges">
                {clip.speed !== 1 && <span>⚡{clip.speed}x </span>}
                {clip.volume !== 1 && <span>🔊{clip.volume} </span>}
                {clip.overlays.length > 0 && <span>💬{clip.overlays.length}</span>}
              </div>
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
