// Pure timeline math shared by the preview player and the timeline strip.
// Kept free of React/DOM so it is trivially unit-testable (see timeline.test.ts).

import type { Clip, MediaAsset, Timeline } from "./types";

/** Output duration of a clip in seconds, accounting for speed. */
export function clipDuration(clip: Clip, assets: Map<string, MediaAsset>): number {
  const sourceEnd =
    clip.end ?? assets.get(clip.asset_id)?.duration ?? clip.start;
  return Math.max(0, (sourceEnd - clip.start) / clip.speed);
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
        sourceTime: clip.start + offset * clip.speed,
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
