"""Shared fixtures.

Real ffmpeg (bundled via imageio-ffmpeg) is used for media tests against tiny
synthetic clips - mocking ffmpeg would leave the riskiest code untested.
Anthropic API calls are always mocked; tests never hit the network.
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

# Isolate all app data into a temp dir BEFORE app modules read settings.
_TMP = tempfile.mkdtemp(prefix="ave-test-")
os.environ["DATA_DIR"] = _TMP
os.environ.pop("ANTHROPIC_API_KEY", None)

from app.config import get_settings          # noqa: E402
from app.db import get_engine, reset_engine  # noqa: E402
from app.main import create_app              # noqa: E402
from app.models import MediaAsset            # noqa: E402
from app.services import ffmpeg as ff        # noqa: E402


@pytest.fixture(scope="session")
def settings():
    s = get_settings()
    assert str(s.data_dir) == _TMP, "test data dir isolation failed"
    s.ensure_dirs()
    return s


@pytest.fixture(scope="session")
def sample_clip(settings) -> Path:
    """A 2s 640x360 test video with a sine-tone audio track."""
    path = settings.uploads_dir / "sample_a.mp4"
    if not path.exists():
        ff.generate_test_clip(path, seconds=2.0, with_audio=True)
    return path


@pytest.fixture(scope="session")
def silent_clip(settings) -> Path:
    """A 2s test video with NO audio stream (exercises anullsrc injection)."""
    path = settings.uploads_dir / "sample_silent.mp4"
    if not path.exists():
        ff.generate_test_clip(path, seconds=2.0, with_audio=False)
    return path


@pytest.fixture
def client(settings):
    reset_engine()
    app = create_app()
    with TestClient(app) as c:   # context manager triggers lifespan (job worker)
        yield c


@pytest.fixture
def db_session(client) -> Session:
    with Session(get_engine()) as session:
        yield session


def register_asset(session: Session, path: Path, filename: str | None = None) -> MediaAsset:
    """Insert an existing file as a MediaAsset without going through upload."""
    info = ff.probe(path)
    asset = MediaAsset(
        filename=filename or path.name,
        path=str(path),
        media_type="video",
        duration=info.duration,
        width=info.width,
        height=info.height,
        size_bytes=path.stat().st_size,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
