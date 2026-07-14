"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.listProjects().then(setProjects).catch((e) => setError(String(e.message)));
  }, []);

  useEffect(refresh, [refresh]);

  async function create() {
    if (!name.trim()) return;
    try {
      const project = await api.createProject(name.trim());
      setName("");
      setProjects((p) => [project, ...p]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
      <h1>Agentic Video Editor</h1>
      <p className="muted">
        Create a project, upload media, then edit on the timeline or just tell
        the agent what you want.
      </p>

      <div style={{ display: "flex", gap: 8, margin: "16px 0" }}>
        <input
          style={{ flex: 1 }}
          placeholder="New project name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
        />
        <button className="primary" onClick={create}>Create</button>
      </div>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      <div style={{ display: "grid", gap: 10 }}>
        {projects.map((p) => (
          <Link key={p.id} href={`/editor/${p.id}`} className="project-card">
            <strong>{p.name}</strong>
            <div className="muted">
              {p.timeline.clips.length} clip{p.timeline.clips.length === 1 ? "" : "s"} · updated{" "}
              {new Date(p.updated_at).toLocaleString()}
            </div>
          </Link>
        ))}
        {projects.length === 0 && !error && (
          <p className="muted">No projects yet — create one above.</p>
        )}
      </div>
    </main>
  );
}
