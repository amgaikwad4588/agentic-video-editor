# Agentic Video Editor

A web-based video editor you can drive with natural language. Upload media,
arrange clips on a timeline, preview in the browser — or just tell the agent
*“cut the first 10 seconds, add a title and export”* and it does the edits
through validated tools.

| Layer | Tech | Why (full rationale in [docs/DECISIONS.md](docs/DECISIONS.md)) |
|---|---|---|
| Frontend | Next.js 15, React 19, Konva (react-konva) | official React canvas bindings for the overlay preview |
| Backend | FastAPI, SQLModel/SQLite, asyncio job queue | typed API, zero-ops persistence, non-blocking renders |
| Video engine | FFmpeg (system or bundled via imageio-ffmpeg) | industry-standard server-side rendering |
| Agent | Claude (`claude-opus-4-8`) or Gemini (`gemini-2.5-flash`) tool use | strict-schema tools + validating executor, no fine-tuning needed |
| Deploy | Docker Compose | one command, volume-backed media store |

## Quick start (dev, no Docker)

Prerequisites: **Python 3.13 (standard build — not the free-threaded 3.13t,
see docs/ERRORS-AND-FIXES.md #2)**, **Node 20+**. FFmpeg is optional — a
bundled binary is used automatically if it's not installed.

```bash
# backend
cd backend
py -V:3.13 -m venv .venv            # windows; linux/mac: python3.13 -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
copy .env.example .env               # put your ANTHROPIC_API_KEY in .env (optional)
.venv/Scripts/uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

The frontend proxies `/api/*` to the backend (`next.config.ts` rewrites), so
there is no CORS setup in dev.

The agent chat works with **either** `ANTHROPIC_API_KEY` (Claude) or
`GEMINI_API_KEY` (Google Gemini — has a free tier); set one in `.env`.
Without a key everything else still works and the chat returns a clear 503.

## Deployment

- **Frontend (live):** https://agentic-video-editor-zeta.vercel.app — deployed
  on Vercel from `frontend/`.
- **Backend:** deploy with the one-click [Render Blueprint](render.yaml):
  Render dashboard → New → Blueprint → select this repo → Apply (set
  `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` when prompted). The API can't run
  on Vercel because renders are long-lived background jobs with files on disk.
- **Connect the two:** once the Render service is live, set `BACKEND_URL` to
  its URL in the Vercel project settings (Production env) and redeploy the
  frontend; the `/api/*` rewrite then proxies to it.

## Quick start (Docker)

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
# frontend: http://localhost:3000   backend API docs: http://localhost:8000/docs
```

## Using the agent

Open a project, upload a video, then talk to the right-hand panel:

- “Add beach.mp4 to the timeline”
- “Trim the first clip to 3–8 seconds”
- “Add a caption ‘Day 1’ at the bottom for the first 3 seconds”
- “Speed the second clip up 2x and mute it”
- “Export the video”

The agent inspects the real timeline (`get_timeline` / `list_assets`), applies
validated operations, and the reply lists every action it took. Edits are
persisted only if the whole request succeeds.

## Tests

```bash
# backend — includes real FFmpeg renders against generated fixtures
cd backend && .venv/Scripts/python -m pytest -q

# frontend — pure timeline-math unit tests
cd frontend && npm test
```

## Repository layout

```
backend/
  app/
    config.py            settings (env-overridable)
    models.py            tables + timeline document + API schemas
    db.py                engine/session
    routers/             media, projects, jobs, agent
    services/
      ffmpeg.py          probe/thumbnails/filter-graph/export
      jobs.py            async job queue (Celery upgrade path documented)
      agent/             tool schemas + executor + Claude loop
  tests/                 pytest (API, ffmpeg, agent with fake client)
frontend/
  app/                   pages (project list, editor)
  components/            MediaLibrary, PreviewPlayer(Konva), TimelineStrip,
                         ChatPanel, ExportPanel
  lib/                   typed API client + tested timeline math
docs/
  ARCHITECTURE.md        system design and why
  DECISIONS.md           decision log with sources
  ERRORS-AND-FIXES.md    every real error hit and its fix
  API.md                 endpoint reference
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it fits together, upgrade paths
- [docs/DECISIONS.md](docs/DECISIONS.md) — Konva vs Fabric vs Pixi, server FFmpeg vs wasm, tool-use vs fine-tuning, queue design (with sources)
- [docs/ERRORS-AND-FIXES.md](docs/ERRORS-AND-FIXES.md) — the errors you *will* face (ffprobe missing, concat mismatches, atempo range, drawtext escaping, 3.13t wheels, …)
- [docs/API.md](docs/API.md) — REST reference; live Swagger at `/docs`
