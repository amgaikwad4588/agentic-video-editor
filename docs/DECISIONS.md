# Decision Log

Each entry: what we chose, what we rejected, and why. Sources are from the
research pass done before any code was written (July 2026).

## D1. Canvas library: Konva.js (react-konva) — not Fabric.js or PixiJS

The requirements listed "fabric js, kondla js, fixie js" (Fabric.js, Konva.js,
PixiJS). Comparison research:

| | Fabric.js | Konva.js | PixiJS |
|---|---|---|---|
| Model | object model for design tools | node/scene graph, event system | WebGL renderer |
| React support | community wrappers | **official react-konva** | manual |
| Editor primitives | strong (SVG, text editing) | strong (drag, transform) | none — build everything |

Konva wins for a React/Next.js timeline editor: it is the only one with
official React bindings, and its drag/transform/event primitives map directly
onto "position a text overlay on the preview". PixiJS is a renderer, not an
editor toolkit; Fabric is better for standalone design canvases than for
React-integrated editors.

Sources: [PkgPulse comparison](https://www.pkgpulse.com/guides/fabricjs-vs-konva-vs-pixijs-canvas-2d-graphics-2026),
[Konva "which library"](https://konvajs.org/docs/guides/best-canvas-library.html),
[IMG.LY SDK comparison](https://img.ly/blog/open-source-design-editor-sdks-a-developers-guide-to-choosing-the-right-solution/).

## D2. Rendering: server-side FFmpeg; browser preview without re-encode

"SSMepg" in the requirements = FFmpeg. Options considered:

1. **ffmpeg.wasm in the browser** — private (no upload) but ~8x slower than
   WebCodecs, no GPU access, 2GB memory ceiling, poor for >1080p.
2. **WebCodecs render pipeline** — fast decode/encode but codec-limited,
   Safari/Firefox gaps, and we'd still need FFmpeg for muxing/exotic formats.
3. **Server-side FFmpeg (chosen)** — full codec surface, real CPU, testable
   with pytest, and the standard for production editors' final export.

Preview never re-encodes: the browser plays the source file via
`<video>` + `MediaFragment`-style seeking, and overlays are drawn on a Konva
layer above the video, mirroring what drawtext will burn in at export.

Sources: [VidStudio: WebCodecs vs FFmpeg WASM](https://vidstudio.app/blog/webcodecs-vs-ffmpeg-wasm),
[BurnSub deep-dive](https://burnsub.com/blog/webcodecs-vs-ffmpeg-wasm/),
[Dayverse: why ffmpeg.wasm can't use the GPU](https://dayverse.id/en/articles/why-ffmpeg-wasm-fails-leverage-gpu-acceleration/).

## D3. Agent design: Claude tool use with strict schemas — not fine-tuning

Published agentic-video-editing systems converge on tool-calling:
- **LAVE** (UIST/IUI research): plan-and-execute agent over editing ops.
- **ELLMPEG**: LLM → ffmpeg command generation with self-reflection; even
  with RAG + reflection, raw command generation tops out ~78% accuracy —
  which is exactly why we *don't* let the model write ffmpeg commands.
- **VideoAgent**: workflow generation with feedback loops.

Our agent never emits FFmpeg syntax. It calls typed tools (`trim_clip`,
`add_text_overlay`, ...) validated by a deterministic executor; the backend
alone builds filter graphs. Bad tool input returns `is_error: true` with a
precise message (including valid ids), which the model uses to self-correct —
the same reflection loop ELLMPEG uses, but over a validated action space
instead of free-form shell commands.

Model: `claude-opus-4-8`, adaptive thinking, prompt-cached system prompt +
tool schemas, iteration cap of 12 round trips.

Sources: [ELLMPEG](https://arxiv.org/abs/2602.00028),
[LAVE](https://arxiv.org/html/2402.10294v1),
[VideoAgent](https://github.com/HKUDS/VideoAgent).

## D4. Job queue: asyncio worker with DB-backed state; Celery documented as the scale-out path

Guidance from FastAPI production literature: BackgroundTasks for fire-and-forget
under ~30s; a real queue (Celery/ARQ) for long, retryable, crash-safe work.
Video export is the latter — but a broker on a single-node deployment is ops
weight without capacity. Chosen middle: durable `Job` rows in SQLite + an
asyncio queue + `asyncio.to_thread` render worker + startup recovery of
orphaned jobs. The HTTP contract already matches the Celery version.

Sources: [FastAPI background tasks docs](https://fastapi.tiangolo.com/tutorial/background-tasks/),
[BackgroundTasks vs ARQ](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/),
[job queue design guide](https://blog.greeden.me/en/2025/12/02/practical-background-processing-with-fastapi-a-job-queue-design-guide-with-backgroundtasks-and-celery/).

## D5. SQLite + SQLModel, not Postgres

Single-writer workload (one job worker), tiny row counts, and the whole DB
access layer goes through SQLAlchemy — moving to Postgres is a URL change
(`DATABASE_URL`). Zero-ops beats theoretical concurrency here.

## D6. imageio-ffmpeg as the dev/CI fallback binary

Windows dev machines and CI runners often lack ffmpeg. `imageio-ffmpeg` ships
a static binary per platform, so `pip install` is the only setup step. The
trade-off (no bundled ffprobe) is handled in code — see ERRORS-AND-FIXES.md #1.

## D7. Web-first; Electron as a packaging follow-up

"Web based" and "electron app" were both listed. They aren't in conflict —
an Electron shell wraps the same frontend + backend. We ship web-first
because every Electron feature depends on the web app existing, and document
the packaging path in ARCHITECTURE.md.

## D8. "media 1e library" interpreted as MediaPipe/Media processing — deferred

The requirement line is ambiguous. Candidate readings (MediaPipe for
on-device ML effects; MSE/Media Source Extensions) are both additive
features, not foundations. Deferred until the intent is clarified; the
timeline/overlay model can host either.
