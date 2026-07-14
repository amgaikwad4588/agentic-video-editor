# Architecture

## System overview

```
┌────────────────────────────┐        ┌──────────────────────────────────┐
│  Frontend (Next.js 15)     │  HTTP  │  Backend (FastAPI)               │
│  - Media library           │ ─────► │  /api/media     upload/probe     │
│  - Timeline editor         │        │  /api/projects  timeline CRUD    │
│  - Konva preview canvas    │        │  /api/.../export  render jobs    │
│  - Agent chat panel        │        │  /api/.../agent   NL editing     │
└────────────────────────────┘        └───────┬──────────────┬───────────┘
                                              │              │
                                     ┌────────▼─────┐  ┌─────▼──────────┐
                                     │ SQLite       │  │ Job queue      │
                                     │ (SQLModel)   │  │ (asyncio +     │
                                     │ projects,    │  │  worker thread)│
                                     │ assets, jobs │  └─────┬──────────┘
                                     └──────────────┘        │
                                              ┌──────────────▼───────────┐
                                              │ FFmpeg                   │
                                              │ probe / thumbs / render  │
                                              └──────────────────────────┘
                                              ┌──────────────────────────┐
                                              │ Claude API (tool use)    │
                                              │ claude-opus-4-8          │
                                              └──────────────────────────┘
```

## Why this shape (and not the alternatives)

### Server-side FFmpeg instead of ffmpeg.wasm / WebCodecs rendering
Research (see [DECISIONS.md](DECISIONS.md)) shows modern browser editors use a
hybrid: WebCodecs for real-time preview, WASM/server for final encode.
ffmpeg.wasm encodes 1080p H.264 at ~25 fps with 100% CPU in the browser and
cannot use hardware acceleration; server-side FFmpeg is an order of magnitude
faster and supports every codec. We therefore:
- render **exports on the server** (FFmpeg, libx264 + aac, `+faststart`),
- do **interactive preview in the browser** with `<video>` elements + a Konva
  canvas for overlay positioning (no re-encode needed for preview).

### The timeline is a JSON document, not normalised tables
A timeline is a small, frequently-rewritten ordered tree. Storing clips and
overlays in their own tables would require multi-row transactions on every
drag/trim for zero query benefit at this scale. `Project.timeline` is a JSON
column validated by the `Timeline` Pydantic model at every boundary.

### Job queue: asyncio worker now, Celery later
Export renders are minutes-long and CPU-bound — classic Celery territory.
v1 deliberately uses an in-process `asyncio.Queue` + worker thread because:
- one API node means a broker adds ops cost without adding capacity,
- job state lives in SQLite (`Job` table) either way, so the API contract
  (`202 Accepted` → poll `/api/jobs/{id}`) is identical,
- orphaned jobs are recovered on startup (re-marked `failed`).

**Upgrade path:** replace `jobs.enqueue_export()` internals with
`celery_app.send_task("export", args=[project_id])` and run
`celery -A worker` containers; routers, schemas and the frontend polling
loop stay untouched.

### Agent: tool use, not fine-tuning
The requirements mention "agent finetuning / model architecture designing".
We deliberately do **not** fine-tune a model, for documented reasons:
1. Editing operations are a *closed, structured* action space — exactly what
   LLM tool use is built for. Published systems (LAVE, ELLMPEG, VideoAgent)
   all converge on tool-calling/plan-execute over generation-only models.
2. Fine-tuning would need thousands of (command → edit-plan) pairs we don't
   have, and would freeze the action space into the weights.
3. The "architecture design" work goes into the tool surface instead: strict
   JSON schemas, validating executor, error feedback loop (`is_error: true`
   tool results let the model self-correct), iteration cap, prompt caching.

Agent loop (`app/services/agent/engine.py`):

```
user message ─► Claude (claude-opus-4-8, adaptive thinking, strict tools)
                  │ tool_use blocks
                  ▼
            ToolExecutor (validates against real timeline/assets)
                  │ tool_result (+ is_error on bad input)
                  ▼
             Claude ... repeats ≤ AGENT_MAX_ITERATIONS ... final text
                  │
                  ▼
   timeline persisted only if the whole turn succeeded (all-or-nothing)
```

### FFmpeg binary strategy
Resolution order: `FFMPEG_PATH` env → `PATH` → binary bundled with
`imageio-ffmpeg` (pip). This makes dev machines and CI work with zero system
installs, while Docker installs a full ffmpeg via apt (which also provides
`ffprobe`, though we don't depend on it — see ERRORS-AND-FIXES.md #1).

## Export filter graph

Per clip: `trim` → `setpts/atempo` (speed) → `scale+pad` to 1280x720 →
`fps=30, format=yuv420p` → `drawtext` overlays → `concat` across clips →
`libx264 crf 20 + aac 192k`. Clips without audio get `anullsrc` silence so
`concat`'s `a=1` contract holds. Progress is parsed from `-progress pipe:1`.

## Data layout

```
backend/data/
├── uploads/      original media (random hex names — client names untrusted)
├── renders/      export outputs ({job_id}.mp4)
├── thumbnails/   {asset_id}.jpg
└── editor.db     SQLite
```

## Frontend structure

- `app/page.tsx` — project picker
- `app/editor/[projectId]/page.tsx` — the editor (library / preview / timeline / chat)
- `components/` — MediaLibrary, PreviewPlayer (Konva overlay canvas), Timeline,
  ChatPanel, ExportPanel
- `lib/api.ts` — typed API client; `lib/timeline.ts` — pure timeline math
  (unit-tested with vitest)

## Electron note

The requirements list an Electron app. The web app is Electron-ready by
construction (pure HTTP API + SPA); packaging is a follow-up:
wrap the Next.js build with `electron-builder`, point the renderer at the
bundled backend (spawn uvicorn as a child process), and swap `localhost`
origins for `app://`. Not shipped in v1 to keep the review surface sane.
