"""Gemini engine tests: schema conversion, provider pick, and the loop
with a scripted fake client. No network, no API key."""

from types import SimpleNamespace

import pytest

from app.models import MediaAsset, Timeline
from app.routers.agent import pick_provider
from app.services.agent.gemini import (
    GeminiEngine,
    fill_omitted_nullables,
    gemini_function_declarations,
    to_gemini_schema,
)
from app.services.agent.tools import TOOLS


def make_assets() -> list[MediaAsset]:
    return [MediaAsset(id="a1", filename="beach.mp4", path="x", duration=30.0)]


# ---- schema conversion -------------------------------------------------------

def test_type_unions_become_nullable():
    js = {
        "type": "object",
        "properties": {
            "end": {"type": ["number", "null"], "description": "out point"},
            "name": {"type": "string"},
        },
        "required": ["end", "name"],
        "additionalProperties": False,
    }
    g = to_gemini_schema(js)
    assert g["type"] == "OBJECT"
    assert g["properties"]["end"] == {
        "type": "NUMBER", "nullable": True, "description": "out point",
    }
    assert g["properties"]["name"]["type"] == "STRING"
    # nullable params are dropped from required; additionalProperties dropped
    assert g["required"] == ["name"]
    assert "additionalProperties" not in g


def test_all_tools_convert():
    decls = gemini_function_declarations()
    assert {d["name"] for d in decls} == {t["name"] for t in TOOLS}
    for d in decls:
        assert d["parameters"]["type"] == "OBJECT"


def test_fill_omitted_nullables():
    args = fill_omitted_nullables("add_clip", {"asset_id": "a1", "start": 0})
    assert args["end"] is None and args["position"] is None
    # non-nullable fields are never invented
    assert "speed" not in args


# ---- provider selection --------------------------------------------------------

def test_pick_provider(settings, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert pick_provider() is None
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    assert pick_provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    assert pick_provider() == "anthropic"  # anthropic wins when both set


# ---- engine loop with scripted fake client --------------------------------------

def _fc_part(name, args):
    return SimpleNamespace(function_call=SimpleNamespace(name=name, args=args))


def _text_response(text):
    return SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(function_call=None)]),
    )], text=text)


def _tool_response(*parts):
    return SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=list(parts)),
    )], text=None)


class FakeGeminiClient:
    def __init__(self, responses):
        self.calls = []
        outer = self

        class _Models:
            async def generate_content(self, **kwargs):
                outer.calls.append(kwargs)
                return responses.pop(0)

        self.aio = SimpleNamespace(models=_Models())


@pytest.mark.asyncio
async def test_gemini_engine_executes_tools_then_replies(settings):
    responses = [
        _tool_response(_fc_part("add_clip", {"asset_id": "a1", "start": 0})),
        _text_response("Added beach.mp4 to the timeline."),
    ]
    engine = GeminiEngine(client=FakeGeminiClient(responses))
    reply, actions, ex = await engine.run("add the beach video", Timeline(), make_assets())

    assert "beach" in reply
    assert actions[0].tool == "add_clip"
    # omitted nullable args were defaulted, so the executor succeeded
    assert len(ex.timeline.clips) == 1
    assert ex.mutated


@pytest.mark.asyncio
async def test_gemini_engine_reports_errors_and_caps_iterations(settings):
    looping = _tool_response(_fc_part("trim_clip", {"clip_id": "ghost", "start": 0, "end": 1}))
    engine = GeminiEngine(client=FakeGeminiClient([looping] * 30))
    engine.max_iterations = 3
    from app.services.agent.engine import AgentError
    with pytest.raises(AgentError, match="did not finish"):
        await engine.run("trim it", Timeline(), make_assets())
