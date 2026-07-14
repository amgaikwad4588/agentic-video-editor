"""Async job queue for long-running FFmpeg renders.

Why not Celery/Redis from day one? Export jobs are CPU-bound and minutes-long,
which *is* Celery territory - but Celery adds a broker, a worker deployment
and result-backend ops. v1 runs a single API node, so an asyncio queue with
job state persisted in SQLite gives us:
  - non-blocking API (render runs in a thread via asyncio.to_thread)
  - durable job records (status survives in DB; a crashed "running" job is
    re-marked failed on startup)
  - the exact same Job table/API the Celery version would use.
Upgrade path (documented in docs/ARCHITECTURE.md): swap `enqueue_export` to
`celery_app.send_task(...)` - routers and schemas stay untouched.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..db import get_engine
from ..models import Job, JobStatus, MediaAsset, Project
from . import ffmpeg as ff

log = logging.getLogger(__name__)

_queue: asyncio.Queue[str] | None = None
_worker_task: asyncio.Task | None = None


def _update_job(job_id: str, **fields) -> None:
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


def _run_export(job_id: str, project_id: str) -> None:
    """Blocking render - executed in a worker thread."""
    from ..config import get_settings
    settings = get_settings()

    with Session(get_engine()) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ff.FFmpegError(f"Project {project_id} not found")
        timeline = project.get_timeline()
        asset_ids = {c.asset_id for c in timeline.clips}
        assets = {
            a.id: a for a in session.exec(
                select(MediaAsset).where(MediaAsset.id.in_(asset_ids))  # type: ignore[attr-defined]
            )
        }

    paths = {aid: a.path for aid, a in assets.items()}
    info = {aid: ff.probe(a.path) for aid, a in assets.items()}
    output = settings.renders_dir / f"{job_id}.mp4"

    # Throttle DB writes: only persist progress in 5% steps.
    last = {"p": -1.0}

    def on_progress(p: float) -> None:
        if p - last["p"] >= 0.05 or p >= 1.0:
            last["p"] = p
            _update_job(job_id, progress=round(p, 3))

    ff.export_timeline(timeline, paths, info, output, on_progress)
    _update_job(job_id, status=JobStatus.done, output_path=str(output), progress=1.0)


async def _worker() -> None:
    assert _queue is not None
    while True:
        job_id = await _queue.get()
        try:
            with Session(get_engine()) as session:
                job = session.get(Job, job_id)
            if job is None:
                continue
            _update_job(job_id, status=JobStatus.running)
            await asyncio.to_thread(_run_export, job_id, job.project_id)
            log.info("job %s finished", job_id)
        except Exception as exc:  # noqa: BLE001 - job errors must not kill the worker
            log.exception("job %s failed", job_id)
            _update_job(job_id, status=JobStatus.failed, error=str(exc)[:2000])
        finally:
            _queue.task_done()


async def start_worker() -> None:
    """Called from the FastAPI lifespan. Also recovers orphaned jobs."""
    global _queue, _worker_task
    _queue = asyncio.Queue()
    # Jobs left "running"/"queued" by a previous process can never complete.
    with Session(get_engine()) as session:
        stale = session.exec(
            select(Job).where(Job.status.in_([JobStatus.running, JobStatus.queued]))  # type: ignore[attr-defined]
        ).all()
        for job in stale:
            job.status = JobStatus.failed
            job.error = "Server restarted while job was in flight"
            session.add(job)
        session.commit()
    _worker_task = asyncio.create_task(_worker())


async def stop_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None


async def enqueue_export(project_id: str) -> Job:
    if _queue is None:
        raise RuntimeError("Job worker not started")
    job = Job(project_id=project_id, kind="export")
    with Session(get_engine()) as session:
        session.add(job)
        session.commit()
        session.refresh(job)
    await _queue.put(job.id)
    return job
