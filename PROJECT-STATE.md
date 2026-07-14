# Project State — Checkpoint

_Last updated: 2026-07-14 (resumed; theme work completed and verified)._

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
