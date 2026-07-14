"""Projects and timeline CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import MediaAsset, Project, ProjectCreate, Timeline, TimelineUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_project(project_id: str, session: Session = Depends(get_session)) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.post("", status_code=201, response_model=Project)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    project = Project(name=body.name)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("", response_model=list[Project])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.exec(select(Project).order_by(Project.updated_at.desc())))  # type: ignore[attr-defined]


@router.get("/{project_id}", response_model=Project)
def read_project(project: Project = Depends(get_project)) -> Project:
    return project


@router.put("/{project_id}/timeline", response_model=Project)
def update_timeline(
    body: TimelineUpdate,
    project: Project = Depends(get_project),
    session: Session = Depends(get_session),
) -> Project:
    timeline = Timeline(clips=body.clips)
    # Reject timelines referencing assets that don't exist - catching this at
    # save time beats a cryptic ffmpeg failure at export time.
    asset_ids = {c.asset_id for c in timeline.clips}
    if asset_ids:
        found = set(session.exec(
            select(MediaAsset.id).where(MediaAsset.id.in_(asset_ids))  # type: ignore[attr-defined]
        ))
        missing = asset_ids - found
        if missing:
            raise HTTPException(422, f"Unknown asset ids: {sorted(missing)}")
    project.set_timeline(timeline)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project: Project = Depends(get_project),
    session: Session = Depends(get_session),
) -> None:
    session.delete(project)
    session.commit()
