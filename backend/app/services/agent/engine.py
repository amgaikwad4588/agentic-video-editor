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

Rules:
- Inspect before you edit: call get_timeline / list_assets when the user \
refers to clips or files, so you use real ids - never invent ids.
- Times are seconds. "First 10 seconds" of a clip means start=0, end=10.
- If the request is ambiguous (e.g. multiple assets match a name), pick the \
most reasonable interpretation and state your assumption in the final reply.
- Only call export_video when the user explicitly asks to export/render/save.
- After finishing, reply with one short paragraph summarising what changed. \
No markdown headers, no tool ids - plain language for a non-technical user.
"""


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
    ) -> tuple[str, list[AgentAction], ToolExecutor]:
        """Run one agent turn. Returns (reply_text, actions, executor)."""
        executor = ToolExecutor(timeline, assets)
        actions: list[AgentAction] = []
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]

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
        else:
            raise AgentError(
                f"Agent did not finish within {self.max_iterations} tool iterations"
            )

        if response is None:  # pragma: no cover - loop always runs once
            raise AgentError("No response from model")

        reply = next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip() or "Done."
        return reply, actions, executor
