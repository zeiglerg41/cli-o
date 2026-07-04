"""Unit tests for the update_plan tool."""

import asyncio

from clio.agent.tools import Tools


def run(coro):
    return asyncio.run(coro)


def make_tools():
    return Tools()


class TestUpdatePlan:
    def test_valid_plan_stored_and_rendered(self):
        tools = make_tools()
        result = run(tools.update_plan(plan=[
            {"step": "Read the file", "status": "completed"},
            {"step": "Edit the file", "status": "in_progress"},
            {"step": "Run tests", "status": "pending"},
        ]))
        assert result.startswith("Plan updated:")
        assert "✔ Read the file" in result
        assert "→ Edit the file" in result
        assert "○ Run tests" in result
        assert tools.current_plan is not None
        assert tools.render_plan() in result

    def test_defaults_missing_status_to_pending(self):
        tools = make_tools()
        result = run(tools.update_plan(plan=[{"step": "Do a thing"}]))
        assert "○ Do a thing" in result

    def test_rejects_multiple_in_progress(self):
        tools = make_tools()
        result = run(tools.update_plan(plan=[
            {"step": "a", "status": "in_progress"},
            {"step": "b", "status": "in_progress"},
        ]))
        assert result.startswith("Error:")
        assert tools.current_plan is None

    def test_rejects_invalid_status(self):
        tools = make_tools()
        result = run(tools.update_plan(plan=[{"step": "a", "status": "done"}]))
        assert result.startswith("Error:")

    def test_rejects_empty_plan(self):
        tools = make_tools()
        assert run(tools.update_plan(plan=[])).startswith("Error:")
        assert run(tools.update_plan(plan=[{"status": "pending"}])).startswith("Error:")

    def test_render_plan_empty_without_plan(self):
        assert make_tools().render_plan() == ""

    def test_tool_definition_registered(self):
        tools = make_tools()
        names = [t["function"]["name"] for t in tools.get_tool_definitions()]
        assert "update_plan" in names

    def test_execute_tool_dispatch(self):
        tools = make_tools()
        result = run(tools.execute_tool("update_plan", {
            "plan": [{"step": "x", "status": "pending"}],
        }))
        assert result.startswith("Plan updated:")
