"use client";

import { useRef, useState } from "react";

import { api } from "@/lib/api";
import { formatTime } from "@/lib/timeline";
import type { MediaAsset } from "@/lib/types";

interface UploadState {
  filename: string;
  fraction: number; // 0..1 network progress; server processing follows
}

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
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function uploadFiles(files: FileList | File[] | null) {
    const list = files ? Array.from(files) : [];
    if (!list.length || upload) return;
    setError(null);
    try {
      for (const file of list) {
        setUpload({ filename: file.name, fraction: 0 });
        await api.uploadMedia(file, (fraction) =>
          setUpload({ filename: file.name, fraction }),
        );
        onChanged();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUpload(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const pct = upload ? Math.round(upload.fraction * 100) : 0;

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        uploadFiles(e.dataTransfer.files);
      }}
    >
      <span className="overline">The Archive</span>

      <button
        className="primary upload-btn"
        onClick={() => fileInput.current?.click()}
        disabled={!!upload}
        style={{ marginTop: 12 }}
      >
        {upload ? `Uploading ${pct}%` : "+ Upload footage"}
      </button>
      <input
        ref={fileInput}
        type="file"
        multiple
        accept="video/*,audio/*,image/*"
        hidden
        onChange={(e) => uploadFiles(e.target.files)}
      />

      {upload && (
        <div style={{ marginTop: 10 }}>
          <div className="progress-bar">
            <div style={{ width: `${pct}%` }} />
          </div>
          <div className="upload-status">
            {pct < 100
              ? `Sending ${upload.filename}`
              : `Processing ${upload.filename}, one moment`}
          </div>
        </div>
      )}

      {error && (
        <p className="muted" style={{ fontStyle: "italic", fontSize: 14 }}>{error}</p>
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
              <div className="muted" style={{ fontSize: 12 }}>
                {a.duration != null ? formatTime(a.duration) : "still"}
              </div>
            </div>
            <button title="Add to timeline" onClick={() => onAddToTimeline(a.id)}>+ Add</button>
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
        {assets.length === 0 && !upload && (
          <div
            className={`upload-zone ${dragging ? "drag" : ""}`}
            onClick={() => fileInput.current?.click()}
            role="button"
            aria-label="Upload media"
          >
            <span className="big">Drop footage here</span>
            <span className="hint">or click to browse. Video, audio or images</span>
          </div>
        )}
      </div>
    </div>
  );
}
