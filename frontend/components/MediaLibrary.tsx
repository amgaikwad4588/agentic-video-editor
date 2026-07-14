"use client";

import { useRef, useState } from "react";

import { api } from "@/lib/api";
import { formatTime } from "@/lib/timeline";
import type { MediaAsset } from "@/lib/types";

export default function MediaLibrary({
  assets,
  onChanged,
  onAddToTimeline,
}: {
  assets: MediaAsset[];
  onChanged: () => void;
  onAddToTimeline: (assetId: string) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await api.uploadMedia(file);
      }
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="overline">The Archive</span>
        <button onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? "Uploading…" : "+ Upload"}
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept="video/*,audio/*,image/*"
          hidden
          onChange={(e) => upload(e.target.files)}
        />
      </div>

      {error && (
        <p className="muted" style={{ fontStyle: "italic", fontSize: 12 }}>{error}</p>
      )}

      <div style={{ marginTop: 10 }}>
        {assets.map((a) => (
          <div key={a.id} className="asset-card" title={a.filename}>
            {a.media_type === "video" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={api.thumbnailUrl(a.id)} alt="" loading="lazy" />
            ) : (
              <div style={{ width: 64, textAlign: "center" }}>
                {a.media_type === "audio" ? "🎵" : "🖼️"}
              </div>
            )}
            <div className="name">
              <div>{a.filename}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                {a.duration != null ? formatTime(a.duration) : "—"}
              </div>
            </div>
            <button title="Add to timeline" onClick={() => onAddToTimeline(a.id)}>+</button>
            <button
              className="danger"
              title="Delete asset"
              onClick={async () => {
                await api.deleteMedia(a.id).catch((e) => setError(e.message));
                onChanged();
              }}
            >
              ×
            </button>
          </div>
        ))}
        {assets.length === 0 && (
          <p className="muted serif" style={{ fontStyle: "italic" }}>
            Upload video, audio or images to begin.
          </p>
        )}
      </div>
    </div>
  );
}
