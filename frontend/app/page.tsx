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
    <main>
      <section className="home-hero">
        <p className="overline ruled">Atelier — Vol. 01</p>
        <h1 style={{ marginTop: 28 }}>
          Cut with <em className="italic-accent">intention</em>.
        </h1>
        <p
          className="muted"
          style={{ maxWidth: "44ch", marginTop: 32, fontSize: 16 }}
        >
          A video editor directed by language. Upload your footage, arrange the
          timeline by hand — or simply describe the film you want and let the
          agent compose it.
        </p>

        <div style={{ display: "flex", gap: 20, marginTop: 48, maxWidth: 520 }}>
          <input
            style={{ flex: 1 }}
            placeholder="Name a new project…"
            aria-label="New project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
          />
          <button className="primary" onClick={create}>
            Begin
          </button>
        </div>
        {error && (
          <p className="muted" style={{ marginTop: 16, fontStyle: "italic" }}>
            {error}
          </p>
        )}
      </section>

      <section className="home-content">
        <p className="overline ruled" style={{ marginBottom: 8 }}>
          The Collection — {projects.length} project{projects.length === 1 ? "" : "s"}
        </p>

        <div>
          {projects.map((p) => (
            <Link key={p.id} href={`/editor/${p.id}`} className="project-card">
              <strong>{p.name}</strong>
              <div className="overline" style={{ marginTop: 10 }}>
                {p.timeline.clips.length} clip{p.timeline.clips.length === 1 ? "" : "s"}
                {" · "}
                {new Date(p.updated_at).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </div>
            </Link>
          ))}
          {projects.length === 0 && !error && (
            <p className="muted serif" style={{ fontStyle: "italic", fontSize: 18 }}>
              Nothing here yet — every collection begins with a single piece.
            </p>
          )}
          {projects.length > 0 && <div style={{ borderTop: "1px solid var(--hairline)" }} />}
        </div>
      </section>
    </main>
  );
}
