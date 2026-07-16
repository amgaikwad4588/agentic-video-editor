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

  // Adopt the most recent job on mount so a page refresh mid-render doesn't
  // lose the export (it kept running on the server all along).
  useEffect(() => {
    api
      .listJobs(projectId)
      .then((jobs) => {
        if (jobs.length > 0) setJob(jobs[0]);
      })
      .catch(() => {
        /* no job history is fine */
      });
  }, [projectId]);

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

  const rendering = job?.status === "queued" || job?.status === "running";
  const pct = job ? Math.round(job.progress * 100) : 0;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {error && (
        <span className="muted" style={{ fontStyle: "italic", fontSize: 14 }}>{error}</span>
      )}

      {rendering && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 200 }}>
          <div className="progress-bar" style={{ flex: 1 }}>
            <div style={{ width: `${pct}%` }} />
          </div>
          <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
            {job?.status === "queued" || pct === 0 ? "starting render" : `rendering ${pct}%`}
          </span>
        </div>
      )}

      {job?.status === "done" && (
        <a href={api.downloadUrl(job.id)} download>
          <button className="primary">⬇ Download MP4</button>
        </a>
      )}

      {job?.status === "failed" && (
        <span
          className="muted"
          style={{
            fontSize: 12,
            fontStyle: "italic",
            maxWidth: 320,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            borderBottom: "1px solid var(--accent)",
          }}
          title={job.error ?? "Export failed"}
        >
          Export failed: {job.error ?? "unknown error"}
        </span>
      )}

      <button onClick={start} disabled={!hasClips || rendering}>
        {job?.status === "failed" ? "Retry export" : rendering ? "Exporting" : "Export"}
      </button>
    </div>
  );
}
