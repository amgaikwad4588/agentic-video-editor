// Mirrors the backend Pydantic/SQLModel schemas (backend/app/models.py).

export interface MediaAsset {
  id: string;
  filename: string;
  media_type: "video" | "audio" | "image";
  duration: number | null;
  width: number | null;
  height: number | null;
  size_bytes: number;
  created_at: string;
}

export interface TextOverlay {
  text: string;
  x: string;
  y: string;
  font_size: number;
  color: string;
  start: number;
  end: number | null;
}

export type ClipFilter =
  | "none"
  | "grayscale"
  | "sepia"
  | "vivid"
  | "warm"
  | "cool"
  | "vintage"
  | "matte"
  | "noir";

/** One speed-ramp point: from `at` (source seconds after the clip's
 * in-point) onward, play at `speed` until the next point. */
export interface SpeedPoint {
  at: number;
  speed: number;
}

/** One transform keyframe at `at` clip-output seconds; values interpolate
 * linearly between keyframes. x/y are pixel offsets from the canvas centre
 * in 1280x720 export coordinates; rotation is degrees. */
export interface Keyframe {
  at: number;
  scale: number;
  x: number;
  y: number;
  rotation: number;
}

export interface Clip {
  id: string;
  asset_id: string;
  start: number;
  end: number | null;
  speed: number;
  /** Non-empty overrides `speed` (piecewise-constant velocity curve). */
  speed_ramp: SpeedPoint[];
  /** Transform animation over the clip's output time; empty = none. */
  keyframes: Keyframe[];
  volume: number;
  fade_in: number;
  fade_out: number;
  filter: ClipFilter;
  overlays: TextOverlay[];
}

export interface Timeline {
  clips: Clip[];
}

export interface Project {
  id: string;
  name: string;
  timeline: Timeline;
  created_at: string;
  updated_at: string;
}

export type JobStatus = "queued" | "running" | "done" | "failed";

export interface Job {
  id: string;
  project_id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  output_path: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentAction {
  tool: string;
  input: Record<string, unknown>;
  result: string;
}

export interface ChatTurn {
  role: "user" | "agent";
  text: string;
}

export interface AgentResponse {
  reply: string;
  actions: AgentAction[];
  timeline: Timeline;
  // Non-empty when the agent asks a clarifying question; rendered as
  // clickable choices in the chat panel.
  options: string[];
}
