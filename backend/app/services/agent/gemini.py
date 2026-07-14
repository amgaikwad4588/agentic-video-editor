"""Gemini variant of the agent engine (google-genai SDK, function calling).

Same contract as engine.AgentEngine.run(); the router selects this engine
when a GEMINI_API_KEY is configured. The tool definitions and executor are
shared - only the model loop differs.

Two provider quirks handled here:
- Gemini's Schema format doesn't accept JSON-schema type unions like
  ["number", "null"]; they convert to type + nullable=true (uppercase type
  names, no additionalProperties).
- Gemini may omit nullable arguments entirely instead of sending null, so
  missing nullable fields are defaulted to None before dispatch (the shared
  executor signatures require every parameter).
"""

import logging
from typing import Any

from google import genai
from google.genai import types as gtypes

from ...config import get_settings
from ...models import AgentAction, MediaAsset, Timeline
from .engine import SYSTEM_PROMPT, AgentError
from .tools import TOOLS, ToolExecutor

log = logging.getLogger(__name__)

_GEMINI_TYPES = {
    "object": "OBJECT", "string": "STRING", "number": "NUMBER",
    "integer": "INTEGER", "boolean": "BOOLEAN", "array": "ARRAY",
}


def to_gemini_schema(schema: dict) -> dict:
    """Convert a JSON-schema tool input to Gemini's Schema dialect."""
    out: dict[str, Any] = {}
    t = schema.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"] or ["string"]
        out["type"] = _GEMINI_TYPES[non_null[0]]
        out["nullable"] = True
    elif t:
        out["type"] = _GEMINI_TYPES[t]
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = schema["enum"]
    if "properties" in schema:
        out["properties"] = {k: to_gemini_schema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = to_gemini_schema(schema["items"])
    if "required" in schema:
        # Nullable params are optional for Gemini (it omits them rather than
        # sending null); requiring them causes spurious validation failures.
        nullable = {
            k for k, v in schema.get("properties", {}).items()
            if isinstance(v.get("type"), list) and "null" in v["type"]
        }
        required = [k for k in schema["required"] if k not in nullable]
        if required:
            out["required"] = required
    return out


def gemini_function_declarations() -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": to_gemini_schema(t["input_schema"]),
        }
        for t in TOOLS
    ]


# name -> set of nullable parameter names, for defaulting omitted args
_NULLABLE: dict[str, set[str]] = {
    t["name"]: {
        k for k, v in t["input_schema"].get("properties", {}).items()
        if isinstance(v.get("type"), list) and "null" in v["type"]
    }
    for t in TOOLS
}


def fill_omitted_nullables(tool_name: str, args: dict) -> dict:
    for key in _NULLABLE.get(tool_name, ()):
        args.setdefault(key, None)
    return args


class GeminiEngine:
    def __init__(self, client: genai.Client | None = None):
        settings = get_settings()
        if client is not None:
            self.client = client
        else:
            # api_key=None lets the SDK fall back to GEMINI_API_KEY/GOOGLE_API_KEY.
            self.client = genai.Client(api_key=settings.gemini_api_key or None)
        self.model = settings.gemini_model
        self.max_iterations = settings.agent_max_iterations

    async def run(
        self,
        message: str,
        timeline: Timeline,
        assets: list[MediaAsset],
    ) -> tuple[str, list[AgentAction], ToolExecutor]:
        executor = ToolExecutor(timeline, assets)
        actions: list[AgentAction] = []

        config = gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[gtypes.Tool(function_declarations=gemini_function_declarations())],
            temperature=0.2,  # editing ops should be precise, not creative
        )
        contents: list[Any] = [
            gtypes.Content(role="user", parts=[gtypes.Part(text=message)])
        ]

        reply = ""
        for _ in range(self.max_iterations):
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=contents, config=config,
            )
            candidate = response.candidates[0] if response.candidates else None
            parts = list(candidate.content.parts or []) if candidate and candidate.content else []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

            if not calls:
                reply = (response.text or "").strip()
                break

            contents.append(candidate.content)
            result_parts = []
            for call in calls:
                args = fill_omitted_nullables(call.name, dict(call.args or {}))
                try:
                    result = executor.execute(call.name, args)
                except (ValueError, KeyError, TypeError) as exc:
                    result = f"Error: {exc}"
                actions.append(AgentAction(tool=call.name, input=args, result=result))
                result_parts.append(
                    gtypes.Part.from_function_response(
                        name=call.name, response={"result": result},
                    )
                )
            contents.append(gtypes.Content(role="user", parts=result_parts))
        else:
            raise AgentError(
                f"Agent did not finish within {self.max_iterations} tool iterations"
            )

        return reply or "Done.", actions, executor
