"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";

import ChatPanel from "@/components/ChatPanel";
import ExportPanel from "@/components/ExportPanel";
import MediaLibrary from "@/components/MediaLibrary";
import PreviewPlayer from "@/components/PreviewPlayer";
import TimelineStrip from "@/components/TimelineStrip";
import { api } from "@/lib/api";
import type { MediaAsset, Project, Timeline } from "@/lib/types";

export default function EditorPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = use(params);

  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const assetMap = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets]);

  useEffect(() => {
    Promise.all([api.getProject(projectId), api.listMedia()])
      .then(([p, m]) => {
        setProject(p);
        setAssets(m);
      })
      .catch((e) => setError(e.message));
  }, [projectId]);

  const saveTimeline = useCallback(
    async (timeline: Timeline) => {
      // Optimistic update; server response is authoritative.
      setProject((p) => (p ? { ...p, timeline } : p));
      try {
        const saved = await api.updateTimeline(projectId, timeline.clips);
        setProject(saved);
      } catch (e) {
        setError((e as Error).message);
        const fresh = await api.getProject(projectId);
        setProject(fresh);
      }
    },
    [projectId],
  );

  const refreshAssets = useCallback(() => {
    api.listMedia().then(setAssets).catch((e) => setError(e.message));
  }, []);

  if (error && !project) {
    return (
      <main style={{ padding: 24 }}>
        <p style={{ color: "var(--danger)" }}>{error}</p>
        <Link href="/">← back to projects</Link>
      </main>
    );
  }
  if (!project) return <main style={{ padding: 24 }}>Loading…</main>;

  return (
    <main>
      <div className="topbar">
        <Link href="/" className="muted">← Projects</Link>
        <h1>{project.name}</h1>
        <div style={{ flex: 1 }} />
        {error && <span style={{ color: "var(--danger)" }}>{error}</span>}
        <ExportPanel projectId={project.id} hasClips={project.timeline.clips.length > 0} />
      </div>

      <div className="editor-grid">
        <div className="panel editor-library">
          <MediaLibrary
            assets={assets}
            onChanged={refreshAssets}
            onAddToTimeline={(assetId) => {
              const clip = {
                id: crypto.randomUUID().replace(/-/g, ""),
                asset_id: assetId,
                start: 0,
                end: null,
                speed: 1,
                volume: 1,
                overlays: [],
              };
              saveTimeline({ clips: [...project.timeline.clips, clip] });
            }}
          />
        </div>

        <div className="panel editor-preview">
          <PreviewPlayer
            timeline={project.timeline}
            assets={assetMap}
            selectedClipId={selectedClipId}
          />
        </div>

        <div className="panel editor-chat">
          <ChatPanel
            projectId={project.id}
            onTimelineChanged={(timeline) =>
              setProject((p) => (p ? { ...p, timeline } : p))
            }
          />
        </div>

        <div className="panel editor-timeline" style={{ gridColumn: "2 / 3" }}>
          <TimelineStrip
            timeline={project.timeline}
            assets={assetMap}
            selectedClipId={selectedClipId}
            onSelect={setSelectedClipId}
            onChange={saveTimeline}
          />
        </div>
      </div>
    </main>
  );
}
