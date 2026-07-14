"""Media library: upload, probe, list, thumbnails, raw file serving."""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..models import MediaAsset
from ..services import ffmpeg as ff

router = APIRouter(prefix="/api/media", tags=["media"])

_AUDIO = {".mp3", ".wav", ".aac", ".m4a", ".flac"}
_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@router.post("", status_code=201, response_model=MediaAsset)
async def upload_media(file: UploadFile, session: Session = Depends(get_session)) -> MediaAsset:
    settings = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_upload_extensions:
        raise HTTPException(415, f"Unsupported file type '{ext}'")

    # Random name on disk: never trust client filenames for paths.
    dest = settings.uploads_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit")
                out.write(chunk)

        media_type = "audio" if ext in _AUDIO else "image" if ext in _IMAGE else "video"
        try:
            info = ff.probe(dest)
        except ff.FFmpegError as exc:
            raise HTTPException(422, f"File is not a valid media file: {exc}")

        asset = MediaAsset(
            filename=file.filename or dest.name,
            path=str(dest),
            media_type=media_type,
            duration=info.duration,
            width=info.width,
            height=info.height,
            size_bytes=size,
        )
        if info.has_video:
            thumb = settings.thumbnails_dir / f"{asset.id}.jpg"
            try:
                ff.make_thumbnail(dest, thumb, at=min(0.5, (info.duration or 1) / 2))
            except ff.FFmpegError:
                pass  # thumbnail failures must not block upload
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("", response_model=list[MediaAsset])
def list_media(session: Session = Depends(get_session)) -> list[MediaAsset]:
    return list(session.exec(select(MediaAsset).order_by(MediaAsset.created_at.desc())))  # type: ignore[attr-defined]


@router.get("/{asset_id}/file")
def get_media_file(asset_id: str, session: Session = Depends(get_session)) -> FileResponse:
    asset = session.get(MediaAsset, asset_id)
    if asset is None or not Path(asset.path).is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(asset.path, filename=asset.filename)


@router.get("/{asset_id}/thumbnail")
def get_thumbnail(asset_id: str, session: Session = Depends(get_session)) -> FileResponse:
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    thumb = get_settings().thumbnails_dir / f"{asset_id}.jpg"
    if not thumb.is_file():
        raise HTTPException(404, "No thumbnail for this asset")
    return FileResponse(thumb)


@router.delete("/{asset_id}", status_code=204)
def delete_media(asset_id: str, session: Session = Depends(get_session)) -> None:
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    session.delete(asset)
    session.commit()
    Path(asset.path).unlink(missing_ok=True)
    (get_settings().thumbnails_dir / f"{asset_id}.jpg").unlink(missing_ok=True)
