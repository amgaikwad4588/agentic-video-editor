"""Application configuration.

All settings can be overridden with environment variables (or a .env file),
e.g. ``DATA_DIR=/var/media uvicorn app.main:app``. Defaults are chosen so the
app runs out of the box on a dev machine with zero configuration.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Agentic Video Editor API"
    debug: bool = False

    # Storage layout: everything lives under data_dir so a single volume mount
    # covers uploads, renders and the SQLite database in Docker.
    data_dir: Path = BACKEND_ROOT / "data"

    # SQLite is deliberate for v1: single-node, zero-ops, safe with our
    # single-writer job queue. The upgrade path to Postgres is changing this
    # URL - all access goes through SQLModel/SQLAlchemy.
    database_url: str = ""

    # Explicit ffmpeg path wins; otherwise we fall back to PATH, then to the
    # binary bundled with imageio-ffmpeg (see services/ffmpeg.py).
    ffmpeg_path: str = ""

    # drawtext requires a font file; the default differs per OS and is
    # resolved lazily in services/ffmpeg.py when this is empty.
    font_path: str = ""

    # Agent
    anthropic_api_key: str = ""
    agent_model: str = "claude-opus-4-8"
    agent_max_tokens: int = 16000
    # Safety valve for the tool-use loop; each iteration is one API round trip.
    agent_max_iterations: int = 12

    # Upload constraints
    max_upload_mb: int = 1024
    allowed_upload_extensions: set[str] = {
        ".mp4", ".mov", ".mkv", ".webm", ".avi",
        ".mp3", ".wav", ".aac", ".m4a", ".flac",
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
    }

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'editor.db'}"

    def ensure_dirs(self) -> None:
        for d in (self.uploads_dir, self.renders_dir, self.thumbnails_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
