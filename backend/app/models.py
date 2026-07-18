"""Database tables and API schemas.

Two layers on purpose:
- SQLModel ``table=True`` classes are what SQLite stores.
- The timeline itself is a JSON document (list of clips) inside Project.
  A timeline is a small, frequently-rewritten tree; normalising clips and
  overlays into their own tables would force multi-table transactions on
  every drag operation for no query benefit at this scale.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field as PField, model_validator
from sqlmodel import JSON, Column, Field, SQLModel


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Timeline document (stored as JSON inside Project.timeline)
# --------------------------------------------------------------------------

class TextOverlay(BaseModel):
    """A text label burned into a clip during export (drawtext)."""
    text: str
    x: str = "(w-text_w)/2"   # ffmpeg drawtext expressions; centered by default
    y: str = "h-th-40"
    font_size: int = PField(default=48, ge=8, le=400)
    color: str = "white"
    start: float = 0.0        # seconds relative to the clip
    end: float | None = None  # None = until clip end


CLIP_FILTERS = (
    "none", "grayscale", "sepia",
    "vivid", "warm", "cool", "vintage", "matte", "noir",
)


class SpeedPoint(BaseModel):
    """One point of a speed ramp: from `at` (source seconds after the clip's
    in-point) onward, play at `speed` until the next point."""
    at: float = PField(ge=0)
    speed: float = PField(gt=0.09, lt=10.1)


class Keyframe(BaseModel):
    """One transform keyframe, in clip OUTPUT seconds. Values are linearly
    interpolated between keyframes; before the first / after the last the
    nearest keyframe's values hold."""
    at: float = PField(ge=0)
    scale: float = PField(default=1.0, gt=0.05, le=5.0)
    # Pixel offset from the canvas centre (1280x720 export coordinates).
    x: float = PField(default=0.0, ge=-2000, le=2000)
    y: float = PField(default=0.0, ge=-2000, le=2000)
    rotation: float = PField(default=0.0, ge=-360, le=360)  # degrees


class Clip(BaseModel):
    """One segment on the timeline referencing a source asset."""
    id: str = PField(default_factory=_id)
    asset_id: str
    # Source in/out points in seconds. end=None means natural end of asset.
    start: float = PField(default=0.0, ge=0)
    end: float | None = None
    speed: float = PField(default=1.0, gt=0.09, lt=10.1)
    # Speed ramp (VN-style velocity): piecewise-constant speed segments.
    # Non-empty overrides `speed`; first point must be at=0, points strictly
    # ascending.
    speed_ramp: list[SpeedPoint] = PField(default_factory=list)
    # Transform keyframes (VN-style): animate zoom/position/rotation over the
    # clip's output time. Empty = no animation.
    keyframes: list[Keyframe] = PField(default_factory=list)
    volume: float = PField(default=1.0, ge=0.0, le=5.0)
    # Fade durations in output seconds (0 = no fade); applied to video+audio.
    fade_in: float = PField(default=0.0, ge=0.0, le=30.0)
    fade_out: float = PField(default=0.0, ge=0.0, le=30.0)
    # Colour treatment burned in at export and mirrored in the preview.
    filter: str = PField(default="none", pattern=f"^({'|'.join(CLIP_FILTERS)})$")
    overlays: list[TextOverlay] = PField(default_factory=list)

    @model_validator(mode="after")
    def _check_ramp(self) -> "Clip":
        if self.speed_ramp:
            if self.speed_ramp[0].at != 0:
                raise ValueError("speed_ramp must start with a point at=0")
            ats = [p.at for p in self.speed_ramp]
            if any(b <= a for a, b in zip(ats, ats[1:])):
                raise ValueError("speed_ramp points must be strictly ascending")
        kf_ats = [k.at for k in self.keyframes]
        if any(b <= a for a, b in zip(kf_ats, kf_ats[1:])):
            raise ValueError("keyframes must be strictly ascending in `at`")
        return self


class Timeline(BaseModel):
    clips: list[Clip] = PField(default_factory=list)

    def find_clip(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

class MediaAsset(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    filename: str
    path: str
    media_type: str = "video"           # video | audio | image
    duration: float | None = None       # seconds; None for images
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=_now)


class Project(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    name: str
    timeline: dict = Field(default_factory=lambda: {"clips": []}, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def get_timeline(self) -> Timeline:
        return Timeline.model_validate(self.timeline)

    def set_timeline(self, timeline: Timeline) -> None:
        self.timeline = timeline.model_dump()
        self.updated_at = _now()


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Job(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str
    kind: str = "export"
    status: JobStatus = JobStatus.queued
    progress: float = 0.0               # 0..1
    output_path: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --------------------------------------------------------------------------
# API request/response schemas
# --------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = PField(min_length=1, max_length=200)


class TimelineUpdate(BaseModel):
    clips: list[Clip]


class ChatTurn(BaseModel):
    """One prior message in the agent conversation, replayed for context."""
    role: str = PField(pattern="^(user|agent)$")
    text: str = PField(min_length=1, max_length=4000)


class AgentRequest(BaseModel):
    message: str = PField(min_length=1, max_length=4000)
    # Recent conversation history so follow-ups ("the second one", answers to
    # clarifying questions) keep their context across turns.
    history: list[ChatTurn] = PField(default_factory=list, max_length=40)


class AgentAction(BaseModel):
    tool: str
    input: dict
    result: str


class AgentResponse(BaseModel):
    reply: str
    actions: list[AgentAction]
    timeline: Timeline
    # Non-empty when the agent asked a clarifying question: the UI renders
    # these as clickable choices.
    options: list[str] = PField(default_factory=list)
