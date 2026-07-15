"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

export default function ExportPanel({
  projectId,
  hasClips,
}: {
  projectId: string;
  hasClips: boolean;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll while a job is in flight.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        setJob(await api.getJob(job.id));
      } catch {
        /* transient poll errors are fine */
      }
    }, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job?.id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setError(null);
    try {
      setJob(await api.startExport(projectId));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {error && (
        <span className="muted" style={{ fontStyle: "italic", fontSize: 14 }}>{error}</span>
      )}

      {job?.status === "queued" || job?.status === "running" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 180 }}>
          <div className="progress-bar" style={{ flex: 1 }}>
            <div style={{ width: `${Math.round(job.progress * 100)}%` }} />
          </div>
          <span className="muted" style={{ fontSize: 12 }}>
            {job.status === "queued" ? "queued" : `${Math.round(job.progress * 100)}%`}
          </span>
        </div>
      ) : null}

      {job?.status === "done" && (
        <a href={api.downloadUrl(job.id)} download>
          <button className="primary">⬇ Download MP4</button>
        </a>
      )}
      {job?.status === "failed" && (
        <span
          className="overline"
          style={{ borderBottom: "1px solid var(--accent)" }}
          title={job.error ?? ""}
        >
          Export failed
        </span>
      )}

      <button onClick={start} disabled={!hasClips || job?.status === "running" || job?.status === "queued"}>
        Export
      </button>
    </div>
  );
}
