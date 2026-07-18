import { describe, expect, it } from "vitest";

import {
  clipAtTime, clipDuration, clipStartTime, formatTime, moveClip, timelineDuration,
} from "./timeline";
import type { Clip, MediaAsset, Timeline } from "./types";

const asset = (id: string, duration: number): MediaAsset => ({
  id, filename: `${id}.mp4`, media_type: "video", duration,
  width: 1280, height: 720, size_bytes: 1, created_at: "",
});

const clip = (over: Partial<Clip>): Clip => ({
  id: Math.random().toString(36).slice(2),
  asset_id: "a", start: 0, end: null, speed: 1, speed_ramp: [], volume: 1,
  fade_in: 0, fade_out: 0, filter: "none", overlays: [],
  ...over,
});

const assets = new Map([["a", asset("a", 30)], ["b", asset("b", 10)]]);

describe("clipDuration", () => {
  it("uses explicit in/out points", () => {
    expect(clipDuration(clip({ start: 2, end: 12 }), assets)).toBe(10);
  });
  it("falls back to asset duration when end is null", () => {
    expect(clipDuration(clip({ start: 5 }), assets)).toBe(25);
  });
  it("divides by speed", () => {
    expect(clipDuration(clip({ start: 0, end: 10, speed: 2 }), assets)).toBe(5);
  });
  it("never goes negative", () => {
    expect(clipDuration(clip({ start: 50 }), assets)).toBe(0);
  });
});

describe("timelineDuration", () => {
  it("sums output durations", () => {
    const tl: Timeline = {
      clips: [clip({ start: 0, end: 10 }), clip({ asset_id: "b", speed: 2 })],
    };
    expect(timelineDuration(tl, assets)).toBe(15); // 10 + 10/2
  });
  it("is 0 for an empty timeline", () => {
    expect(timelineDuration({ clips: [] }, assets)).toBe(0);
  });
});

describe("clipAtTime", () => {
  const tl: Timeline = {
    clips: [
      clip({ id: "c1", start: 5, end: 15 }),           // output 0..10
      clip({ id: "c2", asset_id: "b", speed: 2 }),      // output 10..15
    ],
  };

  it("finds the first clip and maps source time", () => {
    const pos = clipAtTime(tl, assets, 3)!;
    expect(pos.clip.id).toBe("c1");
    expect(pos.sourceTime).toBe(8); // 5 + 3*1
  });

  it("finds the second clip with speed-corrected source time", () => {
    const pos = clipAtTime(tl, assets, 12)!;
    expect(pos.clip.id).toBe("c2");
    expect(pos.offsetInClip).toBe(2);
    expect(pos.sourceTime).toBe(4); // 0 + 2*2
  });

  it("clamps the very end onto the last clip", () => {
    expect(clipAtTime(tl, assets, 15)!.clip.id).toBe("c2");
  });

  it("returns null for an empty timeline", () => {
    expect(clipAtTime({ clips: [] }, assets, 0)).toBeNull();
  });
});

describe("speed ramps", () => {
  // 0-10s source: 0-4s at 1x (4s out), 4-10s at 2x (3s out) => 7s output.
  const ramped = clip({
    id: "r1", start: 0, end: 10,
    speed_ramp: [{ at: 0, speed: 1 }, { at: 4, speed: 2 }],
  });

  it("clipDuration sums ramp segments", () => {
    expect(clipDuration(ramped, assets)).toBe(7);
  });

  it("clipAtTime maps source time through the active segment", () => {
    const tl: Timeline = { clips: [ramped] };
    const early = clipAtTime(tl, assets, 2)!;
    expect(early.sourceTime).toBe(2);
    expect(early.speed).toBe(1);
    const late = clipAtTime(tl, assets, 5)!; // 1s into the 2x segment
    expect(late.sourceTime).toBe(6); // 4 + 1*2
    expect(late.speed).toBe(2);
  });

  it("ignores ramp points beyond the clip's out-point", () => {
    const c = clip({
      start: 0, end: 5,
      speed_ramp: [{ at: 0, speed: 1 }, { at: 8, speed: 4 }],
    });
    expect(clipDuration(c, assets)).toBe(5);
  });
});

describe("clipStartTime", () => {
  it("accumulates prior clip durations", () => {
    const tl: Timeline = {
      clips: [clip({ start: 0, end: 10 }), clip({ start: 0, end: 4 })],
    };
    expect(clipStartTime(tl, assets, 1)).toBe(10);
  });
});

describe("formatTime", () => {
  it("formats mm:ss.d", () => {
    expect(formatTime(75.25)).toBe("1:15.3"); // toFixed rounds
    expect(formatTime(0)).toBe("0:00.0");
  });
  it("handles junk", () => {
    expect(formatTime(NaN)).toBe("0:00.0");
    expect(formatTime(-3)).toBe("0:00.0");
  });
});

describe("moveClip", () => {
  const tl: Timeline = { clips: [clip({ id: "x" }), clip({ id: "y" }), clip({ id: "z" })] };
  it("reorders immutably", () => {
    const out = moveClip(tl, 0, 2);
    expect(out.clips.map((c) => c.id)).toEqual(["y", "z", "x"]);
    expect(tl.clips.map((c) => c.id)).toEqual(["x", "y", "z"]);
  });
  it("clamps out-of-range targets", () => {
    expect(moveClip(tl, 2, 99).clips.map((c) => c.id)).toEqual(["x", "y", "z"]);
  });
});
