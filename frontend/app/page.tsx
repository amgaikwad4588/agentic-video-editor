"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(() => {
    api
      .listProjects()
      .then((p) => {
        setProjects(p);
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true));
  }, []);

  useEffect(refresh, [refresh]);

  async function create() {
    if (!name.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject(name.trim());
      setName("");
      setProjects((p) => [project, ...p]);
      setBackendDown(false);
    } catch (e) {
      const msg = (e as Error).message;
      // A failed fetch (or proxy 502/404) means the API isn't reachable —
      // distinguish that from a real validation error.
      if (msg.toLowerCase().includes("fetch") || /50\d|404/.test(msg)) {
        setBackendDown(true);
      } else {
        setError(msg);
      }
    } finally {
      setCreating(false);
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
          <button className="primary" onClick={create} disabled={creating}>
            {creating ? "Opening…" : "Begin"}
          </button>
        </div>

        {backendDown && (
          <div className="notice" role="alert">
            <span className="overline">The studio is dark</span>
            The editing backend isn&apos;t reachable, so projects can&apos;t be
            created or listed. Running locally? Start the API with{" "}
            <code style={{ fontStyle: "normal" }}>uvicorn app.main:app --port 8000</code>.
            Viewing the hosted demo? The API must be deployed and connected —
            see the README&apos;s Deployment section.
          </div>
        )}
        {error && (
          <div className="notice" role="alert">
            <span className="overline">A note from the desk</span>
            {error}
          </div>
        )}
      </section>

      <section className="home-content" style={{ paddingBottom: 96 }}>
        <p className="overline ruled">The Cutting Room — in pictures</p>

        <div className="gallery">
          <figure className="shot shot-main" style={{ margin: 0 }}>
            <span className="vertical-label">Atelier — the cutting room</span>
            <img
              src="/shots/editor.jpg"
              alt="The editor: media archive, cinema preview with a burned-in caption, agent correspondence panel and the timeline"
              width={1600}
              height={1000}
            />
            <figcaption>
              <span>Fig. 01 — The cutting room, mid-session</span>
            </figcaption>
          </figure>

          <div className="shot-side">
            <figure className="shot" style={{ margin: 0 }}>
              <img
                src="/shots/chat.jpg"
                alt="The correspondence panel where you direct the agent in plain language"
                width={640}
                height={860}
              />
              <figcaption>
                <span>Fig. 02 — Directing by correspondence</span>
              </figcaption>
            </figure>
            <figure className="shot" style={{ margin: 0 }}>
              <img
                src="/shots/timeline.jpg"
                alt="The timeline: draggable clips with trim, speed and volume controls"
                width={1200}
                height={420}
              />
              <figcaption>
                <span>Fig. 03 — The cut, clip by clip</span>
              </figcaption>
            </figure>
          </div>
        </div>
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
          {projects.length === 0 && !backendDown && (
            <p className="muted serif" style={{ fontStyle: "italic", fontSize: 18 }}>
              Nothing here yet — every collection begins with a single piece.
            </p>
          )}
          {projects.length === 0 && backendDown && (
            <p className="muted serif" style={{ fontStyle: "italic", fontSize: 18 }}>
              The collection will appear once the studio backend is connected.
            </p>
          )}
          {projects.length > 0 && <div style={{ borderTop: "1px solid var(--hairline)" }} />}
        </div>
      </section>
    </main>
  );
}
