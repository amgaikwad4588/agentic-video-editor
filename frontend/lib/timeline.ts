// Pure timeline math shared by the preview player and the timeline strip.
// Kept free of React/DOM so it is trivially unit-testable (see timeline.test.ts).

import type { Clip, MediaAsset, Timeline } from "./types";

/** Constant-speed pieces of a clip (source in/out + speed). Mirrors the
 * backend's _clip_segments so preview timing matches the export. */
export function clipSegments(
  clip: Clip,
  assets: Map<string, MediaAsset>,
): { srcStart: number; srcEnd: number; speed: number }[] {
  const sourceEnd =
    clip.end ?? assets.get(clip.asset_id)?.duration ?? clip.start;
  const ramp = clip.speed_ramp ?? [];
  if (ramp.length === 0) {
    return [{ srcStart: clip.start, srcEnd: sourceEnd, speed: clip.speed }];
  }
  const pts = ramp.filter((p) => clip.start + p.at < sourceEnd);
  const segs = pts
    .map((p, j) => ({
      srcStart: clip.start + p.at,
      srcEnd:
        j + 1 < pts.length
          ? Math.min(sourceEnd, clip.start + pts[j + 1].at)
          : sourceEnd,
      speed: p.speed,
    }))
    .filter((s) => s.srcEnd > s.srcStart);
  return segs.length > 0
    ? segs
    : [{ srcStart: clip.start, srcEnd: sourceEnd, speed: clip.speed }];
}

/** Output duration of a clip in seconds, accounting for speed (ramped or constant). */
export function clipDuration(clip: Clip, assets: Map<string, MediaAsset>): number {
  return clipSegments(clip, assets).reduce(
    (sum, s) => sum + Math.max(0, (s.srcEnd - s.srcStart) / s.speed),
    0,
  );
}

/** Total output duration of the timeline. */
export function timelineDuration(tl: Timeline, assets: Map<string, MediaAsset>): number {
  return tl.clips.reduce((sum, c) => sum + clipDuration(c, assets), 0);
}

export interface PlayheadPosition {
  clip: Clip;
  clipIndex: number;
  /** Seconds into the clip's OUTPUT (post-speed). */
  offsetInClip: number;
  /** Seek position in the SOURCE file, seconds. */
  sourceTime: number;
  /** Playback speed at this moment (the active ramp segment's, or the clip's). */
  speed: number;
}

/** Map a clip-output offset to (sourceTime, speed) through the clip's segments. */
function locateInClip(
  clip: Clip,
  assets: Map<string, MediaAsset>,
  offset: number,
): { sourceTime: number; speed: number } {
  const segs = clipSegments(clip, assets);
  let remaining = offset;
  for (const s of segs) {
    const segOut = (s.srcEnd - s.srcStart) / s.speed;
    if (remaining <= segOut || s === segs[segs.length - 1]) {
      return {
        sourceTime: s.srcStart + Math.min(remaining, segOut) * s.speed,
        speed: s.speed,
      };
    }
    remaining -= segOut;
  }
  return { sourceTime: clip.start, speed: clip.speed };
}

/** Map a global timeline time to the clip playing at that moment. */
export function clipAtTime(
  tl: Timeline,
  assets: Map<string, MediaAsset>,
  t: number,
): PlayheadPosition | null {
  let acc = 0;
  for (let i = 0; i < tl.clips.length; i++) {
    const clip = tl.clips[i];
    const dur = clipDuration(clip, assets);
    if (t < acc + dur || i === tl.clips.length - 1 && t <= acc + dur + 1e-6) {
      const offset = Math.min(Math.max(0, t - acc), dur);
      return {
        clip,
        clipIndex: i,
        offsetInClip: offset,
        ...locateInClip(clip, assets, offset),
      };
    }
    acc += dur;
  }
  return null;
}

/** Start time of clip `index` on the output timeline. */
export function clipStartTime(
  tl: Timeline,
  assets: Map<string, MediaAsset>,
  index: number,
): number {
  return tl.clips
    .slice(0, index)
    .reduce((sum, c) => sum + clipDuration(c, assets), 0);
}

/** mm:ss.d formatting for the player UI. */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** Immutable reorder helper for drag-and-drop. */
export function moveClip(tl: Timeline, from: number, to: number): Timeline {
  const clips = [...tl.clips];
  const [moved] = clips.splice(from, 1);
  clips.splice(Math.max(0, Math.min(to, clips.length)), 0, moved);
  return { clips };
}
