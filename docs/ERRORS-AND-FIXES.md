# Errors Faced & Fixes

A running log of real problems hit while building this project, why they
happen, and how the code guards against them. (Requirement: "document ...
what error you will face".)

## 1. `imageio-ffmpeg` bundles ffmpeg but **not** ffprobe

**Symptom:** `FileNotFoundError: ffprobe` on any machine relying on the
bundled binary (typical Windows dev box, CI).
**Why:** the pip package intentionally ships only the `ffmpeg` executable.
**Fix:** probing is implemented by parsing `ffmpeg -hide_banner -i <file>`
stderr (`Duration:`, `Stream ... Video:`, `Stream ... Audio:` lines).
`ffmpeg -i` with no output exits non-zero *by design* — the code ignores the
exit code and reads the banner. See `services/ffmpeg.py::probe`.

## 2. Free-threaded Python 3.13t can't install the stack

**Symptom:** `pip install` fails building wheels for `pydantic-core`, `jiter`,
`greenlet`, `watchfiles` (Rust/C builds kicked off, then fail).
**Why:** on this machine `py -3` resolves to the *free-threaded* 3.13t build;
cp313**t** wheels don't exist for most compiled packages, so pip falls back
to source builds that need Rust/MSVC.
**Fix:** create the venv with the standard GIL build: `py -V:3.13 -m venv .venv`.
Documented in README prerequisites.

## 3. `concat` filter fails on mismatched inputs

**Symptom:** `Input link parameters do not match` / silent geometry glitches
when clips come from different sources.
**Why:** the concat filter requires identical resolution, pixel format, fps,
and audio layout across all segments.
**Fix:** every clip is normalised before concat:
`scale=1280:720:force_original_aspect_ratio=decrease,pad=...,fps=30,format=yuv420p`
and audio `aresample=44100,aformat=channel_layouts=stereo`.

## 4. Sources without an audio stream break `concat=a=1`

**Symptom:** `Cannot find a matching stream for unlabeled input pad` when a
screen recording / generated clip has no audio track.
**Fix:** probe records `has_audio`; for silent sources the graph injects
`anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration=<clip_len>`.
Covered by `test_export_two_clips_with_overlay_and_silent_source`.

## 5. `atempo` only accepts factors 0.5–2.0

**Symptom:** `Value 4.0 for parameter 'tempo' out of range [0.5 - 100]` on
older builds, or wrong-pitch output.
**Fix:** speed changes outside [0.5, 2.0] are decomposed into a chain
(`atempo=2.0,atempo=2.0` for 4x). See `_atempo_chain` + unit tests.

## 6. `drawtext` breaks on user text and on Windows font paths

Two separate traps in one filter:
- Apostrophes in overlay text (e.g. `it's`). First attempt escaped `'` with
  backslashes *inside* the quoted value — the filtergraph parser doesn't
  support that, so the quote pairing shifted and a *later* option
  (`enable='between(t,0,1)'`) got truncated at its comma:
  `Missing ')' or too many args in 'between(t'`. The failure surfaces far
  from its cause, which makes it nasty to debug.
  **Fix (test-verified):** the only escape that exists inside single quotes
  is for the quote itself: `'` → `'\''` (close, escaped quote, reopen).
  Plus `expansion=none` on drawtext so `%{...}` sequences in user text are
  rendered literally instead of being expanded.
- Windows font paths contain a drive colon (`C:/Windows/Fonts/arial.ttf`)
  which drawtext parses as an option separator.
  **Fix:** the drive colon is escaped (`C\:/...`) and the path is left
  unquoted; font resolution order is `FONT_PATH` env → per-OS defaults, and
  the Docker image installs `fonts-dejavu`.

## 7. `ffmpeg -i file` "fails" by design during probe

**Symptom:** treating the non-zero exit code of a probe call as an error
makes every probe "fail".
**Why:** with no output file ffmpeg prints stream info then exits 1
("At least one output file must be specified").
**Fix:** probe ignores the exit code and instead validates that the banner
contains parseable stream info; genuinely broken files are detected by
`Invalid data found` in stderr (covered by `test_probe_rejects_garbage`).

## 8. Renders block the event loop if run naively

**Symptom:** every API request hangs for the duration of an export.
**Why:** `subprocess.run` inside an async handler blocks the single event loop.
**Fix:** the job worker runs renders via `asyncio.to_thread`, and the API
returns `202 + job id` immediately; progress is parsed from
`-progress pipe:1` and persisted in ≥5% steps to avoid hammering SQLite.

## 9. Jobs stuck "running" forever after a crash/restart

**Symptom:** UI shows an eternal spinner for jobs that were in flight when
the server died.
**Fix:** on startup the worker marks all `queued`/`running` jobs as `failed`
with reason "Server restarted while job was in flight". (With Celery this
becomes broker re-delivery instead.)

## 10. Client filenames are attacker-controlled

**Risk:** `../../etc/cron.d/x.mp4`-style names, or collisions.
**Fix:** uploads are stored under random hex names; the original filename is
kept only as display metadata. Extension allowlist + size cap + probe
validation reject non-media uploads (tests: `test_upload_rejects_*`).

## 11. Agent hallucinating clip/asset ids

**Symptom:** model calls `trim_clip` with an id it invented.
**Fix (three layers):** system prompt mandates inspect-before-edit; executor
errors list the *valid* ids so the model can retry correctly
(`test_unknown_clip_error_lists_valid_ids`); strict JSON schemas
(`additionalProperties: false` + all fields required) guarantee shape.

## 12. Agent loop can run away

**Risk:** a confused model looping tool calls burns tokens indefinitely.
**Fix:** hard iteration cap (`AGENT_MAX_ITERATIONS`, default 12); exceeding it
raises `AgentError` → HTTP 422, and no timeline mutation is persisted
(all-or-nothing commit after the loop).

## 13. SQLite + multithreaded FastAPI

**Symptom:** `SQLite objects created in a thread can only be used in that
same thread`.
**Fix:** `check_same_thread=False` on the engine; sessions are short-lived
and per-request (FastAPI dependency) or per-operation (job worker), so a
connection is never shared across threads concurrently.

## 14. Export deadlock: reading stdout while stderr is a pipe

**Symptom:** first full-suite test run froze for 20+ minutes; the ffmpeg
process sat at ~1s CPU total (idle), python idle, nothing progressing.
**Why:** `export_timeline` used `Popen(stdout=PIPE, stderr=PIPE)` and read
*only* stdout (the `-progress pipe:1` stream) until EOF. ffmpeg also writes
banner/encoder info to stderr; once the ~64KB stderr pipe buffer filled,
ffmpeg blocked on write while python blocked on stdout read — a textbook
two-pipe deadlock. Small renders slipped under the buffer size, which is why
unit-level runs passed and the full render test hung.
**Fix:** stderr now goes to a temp file (read only post-exit for error
reporting); stdout remains the sole live pipe. `subprocess.run(...,
capture_output=True)` elsewhere is safe because `run()` drains both pipes
concurrently.

## 15. Windows paths inside filter graphs

Backslashes in `fontfile=` are parsed as escapes. **Fix:** all paths fed into
filters are normalised to forward slashes first.

## 16. Per-clip `fps=` filter silently inflates trimmed clips (ffmpeg 4.x)

**Symptom:** a timeline expected to render 1.5s came out 2.5s; per-stream
inspection showed audio correct (1.5s) but video at 75 frames instead of 45.
**Diagnosis (isolated with `-f null` frame counts):**
`trim=0.5:1.5,setpts=...` alone produced the correct 30 frames, but adding
`fps=30` after it inflated the segment to 45 frames — the fps filter in the
bundled ffmpeg 4.2.2 pads back out toward the source duration on flush when
it follows `trim`. Every variant (`start_time=0`, `settb`, multiplicative
setpts, post-fps setpts) reproduced the padding.
**Fix:** frame-rate normalisation moved out of the per-clip chains to a
single output option (`-r 30`, mux-time CFR). The concat filter only
requires matching resolution and pixel format, not frame rate, so per-clip
fps was never necessary. Verified by
`test_export_two_clips_with_overlay_and_silent_source` asserting output
duration ≈ 1.5s.

## 17. Next.js build fails: konva can't resolve `canvas`

**Symptom:** `npm run build` → `Module not found: Can't resolve 'canvas'`
from `konva/lib/index-node.js` via `react-konva`.
**Why:** Next bundles the *server* module graph even for components loaded
with `dynamic(..., { ssr: false })`. konva's Node entry point `require`s the
optional native `canvas` package, which isn't (and shouldn't be) installed —
we only ever render Konva in the browser.
**Fix:** mark it external in `next.config.ts`:
```ts
webpack: (config) => {
  config.externals = [...(config.externals ?? []), { canvas: "commonjs canvas" }];
  return config;
},
```

## 18. Piping build output through `tail` masks the exit code

**Symptom:** a CI-style check reported the frontend build as passing while it
was actually failing (error #17 existed the whole time).
**Why:** `npm run build 2>&1 | tail -25` reports the exit code of `tail`,
not the build. Classic shell pipeline trap.
**Fix / rule:** never gate on a piped command. Either check `PIPESTATUS`,
use `set -o pipefail`, or redirect to a log file and echo `$?` explicitly:
```bash
npm run build > build.log 2>&1; echo "exit: $?"
```
