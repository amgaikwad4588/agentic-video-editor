"""Editing tools exposed to the model, and their executor.

Every tool is small, deterministic and validates its input against the actual
timeline/assets before mutating anything - the model gets a precise error
string back on bad input (is_error=true), which lets it self-correct instead
of hallucinating success. All schemas use strict mode (additionalProperties
false + required) so tool inputs are guaranteed to validate.
"""

import uuid
from typing import Any

from ...models import CLIP_FILTERS, Clip, MediaAsset, TextOverlay, Timeline

# --------------------------------------------------------------------------
# Tool schemas (Anthropic tool-use format, strict)
# --------------------------------------------------------------------------

def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS: list[dict] = [
    {
        "name": "list_assets",
        "description": (
            "List all media assets in the project library with their ids, "
            "filenames and durations. Call this first when the user refers to "
            "a video by name."
        ),
        "strict": True,
        "input_schema": _schema({}, []),
    },
    {
        "name": "get_timeline",
        "description": (
            "Return the current timeline: ordered clips with ids, source asset, "
            "in/out points, speed, volume and text overlays. Call this before "
            "modifying clips so you reference real clip ids."
        ),
        "strict": True,
        "input_schema": _schema({}, []),
    },
    {
        "name": "add_clip",
        "description": (
            "Append a clip to the timeline (or insert at `position`). "
            "`start`/`end` are source in/out points in seconds; omit `end` to "
            "use the full asset."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "asset_id": {"type": "string", "description": "Id from list_assets"},
                "start": {"type": "number", "description": "Source in-point, seconds"},
                "end": {"type": ["number", "null"], "description": "Source out-point, seconds"},
                "position": {"type": ["integer", "null"], "description": "0-based timeline index; null appends"},
            },
            ["asset_id", "start", "end", "position"],
        ),
    },
    {
        "name": "trim_clip",
        "description": "Change a clip's source in/out points (seconds).",
        "strict": True,
        "input_schema": _schema(
            {
                "clip_id": {"type": "string"},
                "start": {"type": "number"},
                "end": {"type": "number"},
            },
            ["clip_id", "start", "end"],
        ),
    },
    {
        "name": "remove_clip",
        "description": "Delete a clip from the timeline.",
        "strict": True,
        "input_schema": _schema({"clip_id": {"type": "string"}}, ["clip_id"]),
    },
    {
        "name": "move_clip",
        "description": "Move a clip to a new 0-based position in the timeline order.",
        "strict": True,
        "input_schema": _schema(
            {"clip_id": {"type": "string"}, "position": {"type": "integer"}},
            ["clip_id", "position"],
        ),
    },
    {
        "name": "set_speed",
        "description": "Set playback speed for a clip (0.1-10.0; 2.0 = twice as fast).",
        "strict": True,
        "input_schema": _schema(
            {"clip_id": {"type": "string"}, "speed": {"type": "number"}},
            ["clip_id", "speed"],
        ),
    },
    {
        "name": "set_volume",
        "description": "Set audio volume for a clip (0.0 = mute, 1.0 = original, up to 5.0).",
        "strict": True,
        "input_schema": _schema(
            {"clip_id": {"type": "string"}, "volume": {"type": "number"}},
            ["clip_id", "volume"],
        ),
    },
    {
        "name": "split_clip",
        "description": (
            "Split a clip into two at a point. `at` is seconds into the clip's "
            "source segment (relative to its in-point). Use this before "
            "removing or reordering part of a clip, e.g. 'cut out the middle'."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "clip_id": {"type": "string"},
                "at": {"type": "number", "description": "Seconds after the clip's in-point"},
            },
            ["clip_id", "at"],
        ),
    },
    {
        "name": "set_fade",
        "description": (
            "Set fade-in/fade-out durations (seconds) on a clip; applies to "
            "both picture and sound. 0 removes a fade."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "clip_id": {"type": "string"},
                "fade_in": {"type": "number", "description": "Seconds, 0-30"},
                "fade_out": {"type": "number", "description": "Seconds, 0-30"},
            },
            ["clip_id", "fade_in", "fade_out"],
        ),
    },
    {
        "name": "apply_filter",
        "description": (
            "Apply a colour look to a clip: 'grayscale' (black and white), "
            "'sepia', 'vivid' (punchy saturation), 'warm' (golden tint), "
            "'cool' (blue tint), 'vintage' (faded film + vignette), 'matte' "
            "(lifted blacks, muted), 'noir' (high-contrast B&W), or 'none' "
            "to remove it."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "clip_id": {"type": "string"},
                "filter": {"type": "string", "enum": list(CLIP_FILTERS)},
            },
            ["clip_id", "filter"],
        ),
    },
    {
        "name": "add_text_overlay",
        "description": (
            "Burn a text caption into a clip. `start`/`end` are seconds relative "
            "to the clip; end=null shows it until the clip ends. `vertical` "
            "places the text top/center/bottom."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "clip_id": {"type": "string"},
                "text": {"type": "string"},
                "start": {"type": "number"},
                "end": {"type": ["number", "null"]},
                "font_size": {"type": "integer"},
                "color": {
                    "type": "string",
                    "description": "ffmpeg color name or 0xRRGGBB, e.g. white, red, 0x00ff00",
                },
                "vertical": {"type": "string", "enum": ["top", "center", "bottom"]},
            },
            ["clip_id", "text", "start", "end", "font_size", "color", "vertical"],
        ),
    },
    {
        "name": "export_video",
        "description": (
            "Render the current timeline to an MP4 file. Call this only when the "
            "user explicitly asks to export/render/save the final video."
        ),
        "strict": True,
        "input_schema": _schema({}, []),
    },
    {
        "name": "ask_user",
        "description": (
            "Ask the user a clarifying question when the request is ambiguous "
            "and guessing could produce the wrong edit (e.g. several assets or "
            "clips could match, or a value like duration/position is unclear). "
            "Give 2-4 short, concrete options for the user to pick from. This "
            "ends the turn; the user's choice arrives as the next message. Do "
            "not call any other tool alongside this one."
        ),
        "strict": True,
        "input_schema": _schema(
            {
                "question": {
                    "type": "string",
                    "description": "The clarifying question shown to the user",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-4 short, concrete choices the user can click",
                },
            },
            ["question", "options"],
        ),
    },
]

_V_POS = {"top": "40", "center": "(h-text_h)/2", "bottom": "h-th-40"}


class ToolExecutor:
    """Applies tool calls to an in-memory Timeline copy.

    The router persists the timeline only after the whole agent turn
    succeeds, so a failed mid-conversation never leaves a half-applied edit.
    """

    def __init__(self, timeline: Timeline, assets: list[MediaAsset]):
        self.timeline = timeline
        self.assets = {a.id: a for a in assets}
        self.export_requested = False
        self.mutated = False
        # Set by ask_user: {"question": str, "options": list[str]}. The engine
        # stops the loop and surfaces it to the user as clickable choices.
        self.pending_question: dict[str, Any] | None = None

    # -- helpers ---------------------------------------------------------

    def _clip(self, clip_id: str) -> Clip:
        clip = self.timeline.find_clip(clip_id)
        if clip is None:
            ids = [c.id for c in self.timeline.clips]
            raise ValueError(f"No clip with id '{clip_id}'. Existing clip ids: {ids}")
        return clip

    def _describe_timeline(self) -> str:
        if not self.timeline.clips:
            return "Timeline is empty."
        lines = []
        for i, c in enumerate(self.timeline.clips):
            asset = self.assets.get(c.asset_id)
            name = asset.filename if asset else c.asset_id
            end = f"{c.end:.2f}s" if c.end is not None else "asset-end"
            extras = ""
            if c.fade_in or c.fade_out:
                extras += f" fade_in={c.fade_in}s fade_out={c.fade_out}s"
            if c.filter != "none":
                extras += f" filter={c.filter}"
            lines.append(
                f"{i}: clip_id={c.id} source='{name}' in={c.start:.2f}s out={end} "
                f"speed={c.speed}x volume={c.volume} overlays={len(c.overlays)}{extras}"
            )
        return "\n".join(lines)

    # -- dispatch --------------------------------------------------------

    def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        return handler(**tool_input)

    # -- tools -----------------------------------------------------------

    def _tool_list_assets(self) -> str:
        if not self.assets:
            return "Media library is empty - the user must upload files first."
        return "\n".join(
            f"asset_id={a.id} file='{a.filename}' type={a.media_type} "
            f"duration={a.duration if a.duration is not None else 'n/a'}s"
            for a in self.assets.values()
        )

    def _tool_get_timeline(self) -> str:
        return self._describe_timeline()

    def _tool_add_clip(self, asset_id: str, start: float, end: float | None,
                       position: int | None) -> str:
        asset = self.assets.get(asset_id)
        if asset is None:
            raise ValueError(
                f"No asset '{asset_id}'. Available: {list(self.assets)}"
            )
        if end is not None and end <= start:
            raise ValueError("end must be greater than start")
        if asset.duration is not None and start >= asset.duration:
            raise ValueError(f"start {start}s is beyond asset duration {asset.duration}s")
        clip = Clip(asset_id=asset_id, start=start, end=end)
        idx = len(self.timeline.clips) if position is None else max(0, min(position, len(self.timeline.clips)))
        self.timeline.clips.insert(idx, clip)
        self.mutated = True
        return f"Added clip {clip.id} at position {idx}.\n{self._describe_timeline()}"

    def _tool_trim_clip(self, clip_id: str, start: float, end: float) -> str:
        if end <= start:
            raise ValueError("end must be greater than start")
        clip = self._clip(clip_id)
        asset = self.assets.get(clip.asset_id)
        if asset and asset.duration is not None and start >= asset.duration:
            raise ValueError(f"start {start}s is beyond source duration {asset.duration}s")
        clip.start, clip.end = start, end
        self.mutated = True
        return f"Clip {clip_id} trimmed to {start:.2f}s-{end:.2f}s."

    def _tool_remove_clip(self, clip_id: str) -> str:
        clip = self._clip(clip_id)
        self.timeline.clips.remove(clip)
        self.mutated = True
        return f"Removed clip {clip_id}.\n{self._describe_timeline()}"

    def _tool_move_clip(self, clip_id: str, position: int) -> str:
        clip = self._clip(clip_id)
        self.timeline.clips.remove(clip)
        idx = max(0, min(position, len(self.timeline.clips)))
        self.timeline.clips.insert(idx, clip)
        self.mutated = True
        return f"Moved clip {clip_id} to position {idx}.\n{self._describe_timeline()}"

    def _tool_set_speed(self, clip_id: str, speed: float) -> str:
        if not 0.1 <= speed <= 10.0:
            raise ValueError("speed must be between 0.1 and 10.0")
        self._clip(clip_id).speed = speed
        self.mutated = True
        return f"Clip {clip_id} speed set to {speed}x."

    def _tool_set_volume(self, clip_id: str, volume: float) -> str:
        if not 0.0 <= volume <= 5.0:
            raise ValueError("volume must be between 0.0 and 5.0")
        self._clip(clip_id).volume = volume
        self.mutated = True
        return f"Clip {clip_id} volume set to {volume}."

    def _tool_split_clip(self, clip_id: str, at: float) -> str:
        clip = self._clip(clip_id)
        asset = self.assets.get(clip.asset_id)
        end = clip.end if clip.end is not None else (
            asset.duration if asset and asset.duration is not None else None
        )
        if end is None:
            raise ValueError(
                "Cannot split: the clip's end is open and the source duration "
                "is unknown. Call trim_clip with an explicit end first."
            )
        if not 0 < at < (end - clip.start):
            raise ValueError(
                f"at must be within the clip: 0 < at < {end - clip.start:.2f}"
            )
        cut = clip.start + at
        second = clip.model_copy(deep=True)
        second.id = uuid.uuid4().hex
        second.start, second.end = cut, end
        clip.end = cut
        # Overlays are clip-relative in output time; hand each to the side it
        # starts on, shifting the second clip's back by the cut offset.
        boundary = at / clip.speed
        first_ov, second_ov = [], []
        for ov in clip.overlays:
            if ov.start < boundary:
                if ov.end is not None:
                    ov.end = min(ov.end, boundary)
                first_ov.append(ov)
            else:
                ov.start -= boundary
                if ov.end is not None:
                    ov.end -= boundary
                second_ov.append(ov)
        clip.overlays, second.overlays = first_ov, second_ov
        # A fade across the cut would double up; keep in on the first half,
        # out on the second.
        clip.fade_out = 0.0
        second.fade_in = 0.0
        idx = self.timeline.clips.index(clip)
        self.timeline.clips.insert(idx + 1, second)
        self.mutated = True
        return (
            f"Split clip {clip_id} at {at:.2f}s into {clip.id} and {second.id}.\n"
            f"{self._describe_timeline()}"
        )

    def _tool_set_fade(self, clip_id: str, fade_in: float, fade_out: float) -> str:
        if not (0.0 <= fade_in <= 30.0 and 0.0 <= fade_out <= 30.0):
            raise ValueError("fades must be between 0 and 30 seconds")
        clip = self._clip(clip_id)
        clip.fade_in, clip.fade_out = fade_in, fade_out
        self.mutated = True
        return f"Clip {clip_id} fades set: in {fade_in}s, out {fade_out}s."

    def _tool_apply_filter(self, clip_id: str, filter: str) -> str:
        if filter not in CLIP_FILTERS:
            raise ValueError(f"filter must be one of {CLIP_FILTERS}")
        self._clip(clip_id).filter = filter
        self.mutated = True
        return f"Clip {clip_id} filter set to {filter}."

    def _tool_add_text_overlay(self, clip_id: str, text: str, start: float,
                               end: float | None, font_size: int, color: str,
                               vertical: str) -> str:
        clip = self._clip(clip_id)
        overlay = TextOverlay(
            text=text, start=start, end=end, font_size=font_size,
            color=color, y=_V_POS[vertical],
        )
        clip.overlays.append(overlay)
        self.mutated = True
        return f"Added overlay '{text}' to clip {clip_id} ({vertical}, {color}, {font_size}px)."

    def _tool_export_video(self) -> str:
        if not self.timeline.clips:
            raise ValueError("Timeline is empty - add clips before exporting")
        self.export_requested = True
        return "Export queued. The render job will run in the background."

    def _tool_ask_user(self, question: str, options: list) -> str:
        if not question.strip():
            raise ValueError("question must not be empty")
        cleaned = [str(o).strip() for o in options if str(o).strip()]
        if not 2 <= len(cleaned) <= 4:
            raise ValueError("provide between 2 and 4 non-empty options")
        self.pending_question = {"question": question.strip(), "options": cleaned}
        return "Question shown to the user. Stop and wait for their choice."
