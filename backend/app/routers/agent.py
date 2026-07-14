"""Agent endpoint: one natural-language message -> applied timeline edits."""

import logging
import os

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..models import AgentRequest, AgentResponse, MediaAsset, Project
from ..services import jobs as job_service
from ..services.agent.engine import AgentEngine, AgentError
from .projects import get_project

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}/agent", tags=["agent"])


@router.post("", response_model=AgentResponse)
async def run_agent(
    body: AgentRequest,
    project: Project = Depends(get_project),
    session: Session = Depends(get_session),
) -> AgentResponse:
    settings = get_settings()
    if not settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            503,
            "Agent is not configured: set ANTHROPIC_API_KEY on the backend "
            "(the rest of the editor works without it).",
        )

    assets = list(session.exec(select(MediaAsset)))
    engine = AgentEngine()

    try:
        reply, actions, executor = await engine.run(
            body.message, project.get_timeline(), assets
        )
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Invalid ANTHROPIC_API_KEY")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Model rate limit hit - try again shortly")
    except anthropic.APIStatusError as exc:
        log.error("Anthropic API error: %s", exc)
        raise HTTPException(502, f"Model API error ({exc.status_code})")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Cannot reach the model API - check network")
    except AgentError as exc:
        raise HTTPException(422, str(exc))

    # Persist edits only after the whole turn succeeded (all-or-nothing).
    if executor.mutated:
        project.set_timeline(executor.timeline)
        session.add(project)
        session.commit()

    if executor.export_requested:
        await job_service.enqueue_export(project.id)

    return AgentResponse(reply=reply, actions=actions, timeline=executor.timeline)
