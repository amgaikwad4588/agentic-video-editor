"""Export jobs: enqueue, poll status, download result."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Job, JobStatus, Project
from ..services import jobs as job_service

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/projects/{project_id}/export", status_code=202, response_model=Job)
async def start_export(project_id: str, session: Session = Depends(get_session)) -> Job:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if not project.get_timeline().clips:
        raise HTTPException(422, "Timeline is empty - nothing to export")
    return await job_service.enqueue_export(project_id)


@router.get("/jobs/{job_id}", response_model=Job)
def read_job(job_id: str, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/projects/{project_id}/jobs", response_model=list[Job])
def list_project_jobs(project_id: str, session: Session = Depends(get_session)) -> list[Job]:
    return list(session.exec(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())  # type: ignore[attr-defined]
    ))


@router.get("/jobs/{job_id}/download")
def download_result(job_id: str, session: Session = Depends(get_session)) -> FileResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.done or not job.output_path:
        raise HTTPException(409, f"Job is {job.status.value}, no output available")
    if not Path(job.output_path).is_file():
        raise HTTPException(410, "Rendered file no longer exists on disk")
    return FileResponse(job.output_path, filename=f"export_{job_id}.mp4", media_type="video/mp4")
