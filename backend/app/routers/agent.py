"""Agent endpoint: one natural-language message -> applied timeline edits.

Two interchangeable engines (same tools/executor, different model loop):
- Anthropic Claude (services/agent/engine.py) - used when ANTHROPIC_API_KEY is set
- Google Gemini  (services/agent/gemini.py)  - used when GEMINI_API_KEY is set
Anthropic wins when both keys exist; AGENT_PROVIDER=anthropic|gemini overrides.
"""

import logging
import os

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from google.genai import errors as genai_errors
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..models import AgentRequest, AgentResponse, MediaAsset, Project
from ..services import jobs as job_service
from ..services.agent.engine import AgentEngine, AgentError
from ..services.agent.gemini import GeminiEngine
from .projects import get_project

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}/agent", tags=["agent"])


def pick_provider() -> str | None:
    """Return 'anthropic' | 'gemini' | None based on config + environment."""
    settings = get_settings()
    has_anthropic = bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
    has_gemini = bool(
        settings.gemini_api_key
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    forced = settings.agent_provider.lower()
    if forced == "anthropic":
        return "anthropic" if has_anthropic else None
    if forced == "gemini":
        return "gemini" if has_gemini else None
    if has_anthropic:
        return "anthropic"
    if has_gemini:
        return "gemini"
    return None


@router.post("", response_model=AgentResponse)
async def run_agent(
    body: AgentRequest,
    project: Project = Depends(get_project),
    session: Session = Depends(get_session),
) -> AgentResponse:
    provider = pick_provider()
    if provider is None:
        raise HTTPException(
            503,
            "Agent is not configured: set ANTHROPIC_API_KEY or GEMINI_API_KEY "
            "on the backend (the rest of the editor works without it).",
        )

    assets = list(session.exec(select(MediaAsset)))
    engine = AgentEngine() if provider == "anthropic" else GeminiEngine()

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
    except genai_errors.APIError as exc:
        log.error("Gemini API error: %s", exc)
        if exc.code == 429:
            raise HTTPException(429, "Model rate limit hit - try again shortly")
        if exc.code in (401, 403):
            raise HTTPException(503, "Invalid GEMINI_API_KEY")
        raise HTTPException(502, f"Model API error ({exc.code})")
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
