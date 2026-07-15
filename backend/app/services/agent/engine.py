"""The agent loop: natural language -> validated tool calls -> timeline edits.

A manual tool-use loop (not the SDK tool runner) because we need to:
  - collect every executed action to show the user an audit trail,
  - return tool errors with is_error=true so the model self-corrects,
  - cap iterations (a runaway loop costs real money).

Model: claude-opus-4-8 with adaptive thinking. Strict tool schemas guarantee
tool inputs validate, so the executor can trust field presence/types.
"""

import logging
from typing import Any

from anthropic import AsyncAnthropic

from ...config import get_settings
from ...models import AgentAction, MediaAsset, Timeline
from .tools import TOOLS, ToolExecutor

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the editing engine of a video editor. You turn the user's natural \
language requests into precise editing operations via the provided tools.

Accuracy rules:
- Every request comes with the current project state (assets and timeline). \
Use those exact asset/clip ids - never invent ids. If you have already made \
edits this turn, call get_timeline before further edits so ids and positions \
are current.
- Times are seconds. "First 10 seconds" of a clip means start=0, end=10. \
"Last 5 seconds" of a 30s clip means start=25, end=30 - compute from the \
real duration, do not guess.
- Do exactly what was asked: no extra edits, no unrequested clips, overlays \
or exports. Only call export_video when the user explicitly asks to \
export/render/save.
- After a multi-step edit, call get_timeline once to verify the result \
matches the request before replying.

When you are not sure:
- If the request is ambiguous and the choice matters (several assets or \
clips could match, the target clip is unclear, or a key value like duration, \
text or position is missing), call ask_user with 2-4 short, concrete \
options. Do not guess and do not call other tools in the same turn.
- If one interpretation is clearly the obvious one, act on it and state the \
assumption in your reply.

Reply style:
- One short paragraph summarising what changed. No markdown headers, no \
tool ids - plain language for a non-technical user.
- Use plain punctuation: commas, periods and colons. Never use em dashes.
"""


def _project_state(executor: ToolExecutor) -> str:
    """Authoritative snapshot injected with the user message: the model gets
    real ids up front instead of spending iterations on discovery calls."""
    return (
        "<project_state>\n"
        "ASSETS:\n" + executor.execute("list_assets", {}) + "\n\n"
        "TIMELINE:\n" + executor.execute("get_timeline", {}) + "\n"
        "</project_state>"
    )


def build_messages(message: str, history: list, state: str) -> list[dict[str, Any]]:
    """History turns as alternating messages; the fresh project state rides
    with the newest user message (older snapshots would be stale)."""
    messages: list[dict[str, Any]] = []
    for turn in history:
        role = "user" if turn.role == "user" else "assistant"
        if messages and messages[-1]["role"] == role:
            # The API requires alternating roles; merge consecutive same-role
            # turns (happens when an error message was dropped client-side).
            messages[-1]["content"] += "\n\n" + turn.text
        else:
            messages.append({"role": role, "content": turn.text})
    content = f"{state}\n\n{message}"
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + content
    else:
        messages.append({"role": "user", "content": content})
    if messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "(conversation resumes)"})
    return messages


class AgentError(RuntimeError):
    pass


class AgentEngine:
    def __init__(self, client: AsyncAnthropic | None = None):
        settings = get_settings()
        if client is not None:
            self.client = client
        elif settings.anthropic_api_key:
            self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        else:
            # AsyncAnthropic() would also read ANTHROPIC_API_KEY from the env;
            # constructing lazily here keeps import-time side effects at zero.
            self.client = AsyncAnthropic()
        self.model = settings.agent_model
        self.max_tokens = settings.agent_max_tokens
        self.max_iterations = settings.agent_max_iterations

    async def run(
        self,
        message: str,
        timeline: Timeline,
        assets: list[MediaAsset],
        history: list | None = None,
    ) -> tuple[str, list[AgentAction], ToolExecutor]:
        """Run one agent turn. Returns (reply_text, actions, executor)."""
        executor = ToolExecutor(timeline, assets)
        actions: list[AgentAction] = []
        messages = build_messages(message, history or [], _project_state(executor))

        response = None
        for _ in range(self.max_iterations):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # The system prompt + tool schemas are identical across all
                    # requests -> prompt-cache them; only messages vary.
                    "cache_control": {"type": "ephemeral"},
                }],
                thinking={"type": "adaptive"},
                tools=TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = executor.execute(block.name, dict(block.input))
                    is_error = False
                except (ValueError, KeyError, TypeError) as exc:
                    result = f"Error: {exc}"
                    is_error = True
                actions.append(AgentAction(tool=block.name, input=dict(block.input), result=result))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                    "is_error": is_error,
                })
            # All parallel tool results must go back in a single user message.
            messages.append({"role": "user", "content": results})
            if executor.pending_question:
                # The agent asked the user to choose; end the turn here and
                # surface the question + options instead of looping on.
                break
        else:
            raise AgentError(
                f"Agent did not finish within {self.max_iterations} tool iterations"
            )

        if response is None:  # pragma: no cover - loop always runs once
            raise AgentError("No response from model")

        if executor.pending_question:
            reply = executor.pending_question["question"]
        else:
            reply = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip() or "Done."
        return reply, actions, executor
