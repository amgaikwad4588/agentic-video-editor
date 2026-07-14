"""Agent tests.

ToolExecutor is tested directly (pure logic). The engine loop is tested with
a scripted fake Anthropic client - no network, no API key.
"""

from types import SimpleNamespace

import pytest

from app.models import Clip, MediaAsset, Timeline
from app.services.agent.engine import AgentEngine, AgentError
from app.services.agent.tools import TOOLS, ToolExecutor
from tests.conftest import register_asset


def make_assets() -> list[MediaAsset]:
    return [
        MediaAsset(id="a1", filename="beach.mp4", path="x", duration=30.0),
        MediaAsset(id="a2", filename="city.mp4", path="y", duration=12.0),
    ]


# ---- ToolExecutor ----------------------------------------------------------

def test_tool_schemas_are_strict():
    for tool in TOOLS:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
        assert "required" in tool["input_schema"]


def test_add_trim_move_remove_flow():
    ex = ToolExecutor(Timeline(), make_assets())

    ex.execute("add_clip", {"asset_id": "a1", "start": 0, "end": 10, "position": None})
    ex.execute("add_clip", {"asset_id": "a2", "start": 2, "end": None, "position": None})
    assert len(ex.timeline.clips) == 2

    first = ex.timeline.clips[0]
    ex.execute("trim_clip", {"clip_id": first.id, "start": 1, "end": 5})
    assert (first.start, first.end) == (1, 5)

    ex.execute("move_clip", {"clip_id": first.id, "position": 1})
    assert ex.timeline.clips[1].id == first.id

    ex.execute("remove_clip", {"clip_id": first.id})
    assert len(ex.timeline.clips) == 1
    assert ex.mutated


def test_unknown_clip_error_lists_valid_ids():
    ex = ToolExecutor(Timeline(clips=[Clip(asset_id="a1")]), make_assets())
    with pytest.raises(ValueError, match="Existing clip ids"):
        ex.execute("trim_clip", {"clip_id": "nope", "start": 0, "end": 1})


def test_add_clip_validates_asset_and_bounds():
    ex = ToolExecutor(Timeline(), make_assets())
    with pytest.raises(ValueError, match="No asset"):
        ex.execute("add_clip", {"asset_id": "ghost", "start": 0, "end": None, "position": None})
    with pytest.raises(ValueError, match="beyond asset duration"):
        ex.execute("add_clip", {"asset_id": "a2", "start": 99, "end": None, "position": None})


def test_speed_and_volume_bounds():
    tl = Timeline(clips=[Clip(id="c1", asset_id="a1")])
    ex = ToolExecutor(tl, make_assets())
    ex.execute("set_speed", {"clip_id": "c1", "speed": 2.0})
    assert tl.clips[0].speed == 2.0
    with pytest.raises(ValueError):
        ex.execute("set_speed", {"clip_id": "c1", "speed": 50})
    with pytest.raises(ValueError):
        ex.execute("set_volume", {"clip_id": "c1", "volume": -1})


def test_overlay_vertical_positions():
    tl = Timeline(clips=[Clip(id="c1", asset_id="a1")])
    ex = ToolExecutor(tl, make_assets())
    ex.execute("add_text_overlay", {
        "clip_id": "c1", "text": "Hi", "start": 0, "end": None,
        "font_size": 48, "color": "white", "vertical": "top",
    })
    assert tl.clips[0].overlays[0].y == "40"


def test_export_requires_clips():
    ex = ToolExecutor(Timeline(), make_assets())
    with pytest.raises(ValueError, match="empty"):
        ex.execute("export_video", {})
    ex2 = ToolExecutor(Timeline(clips=[Clip(asset_id="a1")]), make_assets())
    ex2.execute("export_video", {})
    assert ex2.export_requested


# ---- Engine loop with scripted fake client ---------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.mark.asyncio
async def test_engine_executes_tools_then_replies(settings):
    responses = [
        SimpleNamespace(stop_reason="tool_use", content=[
            _tool_use("t1", "add_clip", {"asset_id": "a1", "start": 0, "end": 10, "position": None}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[
            _text("Added the first 10 seconds of beach.mp4 to your timeline."),
        ]),
    ]
    engine = AgentEngine(client=FakeClient(responses))
    reply, actions, ex = await engine.run("add first 10s of beach", Timeline(), make_assets())

    assert "beach" in reply
    assert len(actions) == 1 and actions[0].tool == "add_clip"
    assert len(ex.timeline.clips) == 1
    # tool_result must be sent back in the second request
    second_call = engine.client.messages.calls[1]
    tool_results = second_call["messages"][-1]["content"]
    assert tool_results[0]["type"] == "tool_result"
    assert tool_results[0]["is_error"] is False


@pytest.mark.asyncio
async def test_engine_reports_tool_errors_to_model(settings):
    responses = [
        SimpleNamespace(stop_reason="tool_use", content=[
            _tool_use("t1", "trim_clip", {"clip_id": "ghost", "start": 0, "end": 1}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[_text("That clip doesn't exist.")]),
    ]
    engine = AgentEngine(client=FakeClient(responses))
    reply, actions, ex = await engine.run("trim it", Timeline(), make_assets())

    assert actions[0].result.startswith("Error:")
    second_call = engine.client.messages.calls[1]
    assert second_call["messages"][-1]["content"][0]["is_error"] is True
    assert not ex.mutated


@pytest.mark.asyncio
async def test_engine_iteration_cap(settings, monkeypatch):
    looping = SimpleNamespace(stop_reason="tool_use", content=[
        _tool_use("t", "get_timeline", {}),
    ])
    engine = AgentEngine(client=FakeClient([looping] * 50))
    engine.max_iterations = 3
    with pytest.raises(AgentError, match="did not finish"):
        await engine.run("loop forever", Timeline(), make_assets())


# ---- Router ------------------------------------------------------------------

def test_agent_endpoint_503_without_key(client, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    pid = client.post("/api/projects", json={"name": "A"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/agent", json={"message": "trim the video"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert "GEMINI_API_KEY" in r.json()["detail"]
