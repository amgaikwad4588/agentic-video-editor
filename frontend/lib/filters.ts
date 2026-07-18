// Colour looks selectable per clip. The `css` value approximates in the
// preview what backend/app/services/ffmpeg.py:_CLIP_FILTERS burns in at
// export - keep both sides in sync when adding a look.

import type { ClipFilter } from "./types";

export const FILTER_LOOKS: Record<ClipFilter, { label: string; css?: string }> = {
  none: { label: "None" },
  grayscale: { label: "B & W", css: "grayscale(1)" },
  sepia: { label: "Sepia", css: "sepia(1)" },
  vivid: { label: "Vivid", css: "saturate(1.45) contrast(1.08)" },
  warm: { label: "Warm", css: "sepia(0.22) saturate(1.25) hue-rotate(-8deg)" },
  cool: { label: "Cool", css: "saturate(1.05) hue-rotate(12deg) brightness(1.02)" },
  vintage: { label: "Vintage", css: "sepia(0.35) saturate(0.85) contrast(0.95)" },
  matte: { label: "Matte", css: "contrast(0.85) saturate(0.85) brightness(1.06)" },
  noir: { label: "Noir", css: "grayscale(1) contrast(1.35)" },
};

export const FILTER_NAMES = Object.keys(FILTER_LOOKS) as ClipFilter[];

export function filterCss(filter: ClipFilter | undefined): string | undefined {
  return filter ? FILTER_LOOKS[filter]?.css : undefined;
}
