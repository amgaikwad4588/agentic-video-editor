# Project State — Checkpoint

_Last updated: 2026-07-18 (VN-parity editing features)._

## Stage: VN-style editing feature pack (2026-07-18) — done, tested, pushed

Four stages, each committed+pushed separately, inspired by the VN mobile
editor's feature set:

1. **Colour look presets** (`e2e4829`): filter list grew from
   grayscale/sepia to vivid, warm, cool, vintage, matte, noir. ffmpeg chains
   in `_CLIP_FILTERS` mirrored by CSS approximations in
   `frontend/lib/filters.ts` (keep in sync). Every preset render-tested.
2. **Speed ramps** (`6dac16b`): `Clip.speed_ramp` = piecewise-constant
   [{at, speed}] points (source-relative, first at=0, ascending); non-empty
   overrides `speed`. Export expands each clip into one trim/setpts chain
   per constant-speed segment. Agent tool `set_speed_ramp`; `set_speed` and
   the inspector's Speed input clear the ramp; `split_clip` splits it.
3. **Transform keyframes** (`f96ccfd`): `Clip.keyframes` =
   [{at, scale, x, y, rotation}] in clip OUTPUT seconds, linear interp via
   generated ffmpeg expressions (`_lerp_expr`), composited on a black canvas.
   Preview mirrors with a CSS transform. Agent tool `set_keyframes`.
   **Required ffmpeg >= 5 -> imageio-ffmpeg pinned 0.6.0 (bundles 7.1)**,
   which surfaced two ffmpeg-7 parser regressions (ERRORS #19/#20): path
   options must be quoted+escaped, and overlay text now goes through
   drawtext `textfile=` sidecar files (no inline text escaping at all).
4. **Multi-track PiP** (this stage): `Clip.track` 0-3 + `Clip.offset`.
   Track 0 concats as before; tracks 1-3 composite via overlay (scale
   without pad, alpha, keyframable transform, adelay+amix audio,
   normalize=0). No speed ramps on overlay clips (validator + tool guard).
   Agent tool `add_pip_clip` (creates a single positioning keyframe).
   Preview renders one absolute <video> per PiP clip; timeline math
   (duration/playhead) counts only track 0; TimelineStrip shows an
   "Overlays" chip row with an At-offset inspector field.

Tests after all four: backend 65/65, frontend 23/23, `next build` exit 0.

## Stage: export reliability + direct-manipulation trimming (2026-07-15, later)

- **Export diagnosis**: live e2e passed both direct to Render and through the
  Vercel proxy (upload -> timeline -> export -> download). The "not working"
  reports were UX: `-preset medium` sat at 0% on the free tier (now
  `veryfast`), a page refresh lost the job (ExportPanel now re-adopts the
  latest job via listJobs on mount), and failures were tooltip-only (error
  text now visible with a Retry button).
- **Trim by dragging**: clip blocks in The Cut have gold edge handles;
  dragging adjusts start/end live (draft state, committed once on release).
  Preview gained a maximize (fullscreen) button.
- Earlier same day: fades/filters/split_clip editing features, dark mode,
  upload progress, landing redesign, ask_user options, history, state
  injection (see sections below).

## Latest stage (2026-07-15) — done, tested, pushed

- **Agent asks instead of guessing**: new `ask_user` tool; on ambiguity the
  agent returns a question + 2-4 options, rendered as clickable buttons in
  ChatPanel. `AgentResponse.options`, `AgentRequest.history` (ChatTurn list,
  last 20 turns sent by the frontend) so answers keep context.
- **Accuracy**: assets + timeline snapshot injected with every message
  (`_project_state` in engine.py); stricter system prompt (real durations,
  verify multi-step edits, no unrequested edits, no em dashes in replies).
  Same behaviour in both engines (Anthropic + Gemini).
- **UI**: five-step type scale (`--text-xs..xl`) in globals.css; body 16px,
  12px floor everywhere (was 10-11px); darker muted grey; option-button
  styling; all em dashes removed from visible frontend copy.
- **Tests**: backend 42/42, frontend 15/15, `next build` exit 0.
- Commits: `agent: clarifying questions...` and `ui: readable type scale...`.

**Live:** frontend https://agentic-video-editor-zeta.vercel.app (Vercel) ·
backend https://agentic-video-editor-api.onrender.com (Render, free tier,
`GEMINI_API_KEY` set). Verified end-to-end through the live site (project
creation round-trips through Render). Agent supports Gemini and Claude,
auto-selected by API key.

This file is the single source of truth for resuming work. It records what is
**done and verified**, what is **in flight**, one **open bug** with its
diagnosis, and the **remaining roadmap**.

---

## 1. What is DONE and verified

### Backend (FastAPI) — complete, all tests green
- Media library API: upload with probe validation, size/extension limits,
  thumbnails, raw file serving, delete. (`backend/app/routers/media.py`)
- Projects + JSON timeline CRUD with asset-id validation. (`routers/projects.py`)
- Export pipeline: FFmpeg filter graph per clip
  (trim → speed → scale/pad → drawtext overlays → concat), silent-source
  audio injection, progress reporting, output-level CFR (`-r 30`).
  (`services/ffmpeg.py`)
- Async job queue with SQLite-persisted job state, startup recovery of
  orphaned jobs, progress polling + download endpoints. (`services/jobs.py`,
  `routers/jobs.py`)
- **Agent layer**: Claude tool-use loop (`claude-opus-4-8`, adaptive thinking,
  prompt-cached system prompt), 10 strict-schema editing tools with a
  validating executor, error feedback (`is_error`) for self-correction,
  iteration cap, all-or-nothing timeline persistence.
  (`services/agent/tools.py`, `services/agent/engine.py`, `routers/agent.py`)
- **Tests: 32/32 pass** (`.venv/Scripts/python -m pytest -q` in `backend/`),
  including real FFmpeg renders on generated fixtures.
- **Live e2e smoke test passed** against a real uvicorn server:
  health → create project → multipart upload → timeline with overlay
  (apostrophe + colon in text) → export job → poll to done → download 51KB MP4.

### Frontend (Next.js 15 + react-konva) — built, unit tests green
- Pages: project picker (`app/page.tsx`), editor
  (`app/editor/[projectId]/page.tsx`).
- Components: MediaLibrary (upload/thumbs/delete), PreviewPlayerInner
  (multi-clip playback, seek, speed/volume, Konva overlay layer mirroring
  drawtext), TimelineStrip (drag reorder + clip inspector), ChatPanel (agent
  chat with action audit trail), ExportPanel (job polling + download).
- Typed API client (`lib/api.ts`), pure timeline math (`lib/timeline.ts`).
- **Tests: 15/15 pass** (`npm test` in `frontend/`).

### Infra & docs — complete
- `docker-compose.yml` (backend + frontend, media volume), backend/frontend
  Dockerfiles, GitHub Actions CI (`.github/workflows/ci.yml`).
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (with research sources),
  `docs/ERRORS-AND-FIXES.md` (16 real errors + fixes), `docs/API.md`, README.

### Pushed commits (origin/main)
1. `docs:` research-backed architecture, decision log, error playbook
2. `backend:` full API + FFmpeg engine + job queue (+agent layer) + 32 tests
3. `frontend:` editor UI + 15 vitest tests
4. `infra:` Docker Compose, CI, README

---

## 2. DONE — Luxury/Editorial design system (user-requested theme)

The user first asked for a "Newsprint" theme, then **switched to
Luxury/Editorial** ("No i want this") — warm alabaster/charcoal monochrome,
metallic gold accent, Playfair Display + Inter, 0px radius, hairline borders,
slow cinematic motion, grayscale→color image reveals.

**Already applied (uncommitted, in working tree):**
- `app/globals.css` — fully rewritten: design tokens as CSS variables
  (`--bg #F9F8F6`, `--fg #1A1A1A`, `--muted-bg #EBE5DE`, `--muted-fg #6C6863`,
  `--accent #D4AF37`), 0 radius everywhere, hairline borders, border-top
  panel pattern, gold slide-in primary button (background-position trick, no
  extra spans), underline-only inputs with italic serif placeholders, noise
  overlay + fixed gridlines, grayscale thumbnails with 1.5s color reveal,
  shadow evolution on cards/clips, `prefers-reduced-motion` support.
- `app/layout.tsx` — Playfair Display + Inter via `next/font/google`
  (CSS variables `--font-display`/`--font-sans`), noise overlay + gridline
  elements.
- `app/page.tsx` — editorial hero ("Cut with *intention*." with gold italic),
  overline-with-rule labels, border-top project cards ("The Collection").
- Editor chrome — topbar with serif title + overline metadata; panel headers
  renamed to overlines: "The Archive" (media), "Correspondence" (chat),
  "The Cut" (timeline); preview frame charcoal with soft shadow; all old
  dark-theme variables (`--danger` etc.) removed from components.
- Frontend unit tests still pass (15/15) after theme changes.

---

## 3. RESOLVED BUG (fixed on resume, 2026-07-14)

**`npm run build` failed**: `Module not found: Can't resolve 'canvas'` from
`konva/lib/index-node.js`. Fixed with webpack externals in `next.config.ts`
(`{ canvas: "commonjs canvas" }`); build now verified with an unpiped exit
code check (`BUILD EXIT CODE: 0`). Both failure modes documented as
ERRORS-AND-FIXES #17 (konva/canvas) and #18 (tail-masked exit codes).

---

## 4. Remaining roadmap (in order)

1. ~~Fix the konva/canvas build failure~~ — done, verified exit 0.
2. ~~Add ERRORS-AND-FIXES #17 / #18~~ — done.
3. ~~Commit + push the theme stage~~ — done.
4. (Optional/backlog, from original requirements)
   - Electron packaging pass (documented path in ARCHITECTURE.md).
   - Celery/Redis scale-out for the job queue (documented upgrade path).
   - Clarify the ambiguous "media 1e library" requirement (see DECISIONS D8).
   - Waveform/thumbnail strips inside timeline clip blocks.
   - Agent chat streaming (SSE) instead of request/response.

---

## 5. How to resume work

```bash
# backend (all green)
cd backend && .venv/Scripts/python -m pytest -q

# frontend unit tests (green)
cd frontend && npm test

# production build (green — verify exit codes unpiped, see ERRORS #18)
cd frontend && npm run build; echo "exit: $?"
```

Environment notes:
- Windows dev box: use `py -V:3.13` (NOT the default free-threaded 3.13t —
  wheels missing; see ERRORS-AND-FIXES #2).
- No ffmpeg install needed (imageio-ffmpeg bundle auto-used; Docker uses apt
  ffmpeg).
- `ANTHROPIC_API_KEY` only needed for the agent chat endpoint; everything
  else works without it.
