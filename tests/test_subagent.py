"""Unit/integration tests for sub-agent dispatch."""

import asyncio
import json
import logging

from clio.agent.core import Agent
from clio.agent.constants import DEFAULT_SYSTEM_PROMPT
from clio.agent.subagent import (
    DISPATCH_AGENT_DEFINITION,
    SUBAGENT_ALLOWED_TOOLS,
    SUBAGENT_SYSTEM_PROMPT,
    run_subagent,
)
from clio.agent.tools import Tools
from clio.config import ConfigManager


class FakeLogger:
    logger = logging.getLogger("subagent-test")
    def __getattr__(self, name):
        if name.startswith("log_"):
            return lambda *a, **k: None
        raise AttributeError(name)


class CaptureDB:
    def __init__(self):
        self.usage_rows = []
    def retrieve_rag_context(self, *a, **k): return []
    def save_plan(self, *a, **k): pass
    def add_usage_stat(self, **kw): self.usage_rows.append(kw)


def make_parent(provider):
    a = object.__new__(Agent)
    a.provider = provider
    a.current_model = "fake"; a.current_provider_name = "local-gpu"
    a.config_manager = ConfigManager()
    a.session_logger = FakeLogger(); a.history_db = CaptureDB(); a.conversation_id = 7
    a.system_prompt = DEFAULT_SYSTEM_PROMPT
    a.original_working_dir = None; a.recent_files = []
    a.tools = Tools(); a.token_callback = None; a.tool_callback = None
    a.messages = []; a.last_prompt_tokens = 0
    a._context_window_cache = {}; a._tool_support_cache = {}
    a.allow_subagents = True; a.max_turns = 20
    async def noop(*args, **kwargs): pass
    a._save_message_with_rag = noop
    return a


class ScriptedSubProvider:
    """First call: sub-agent greps. Second: returns its report."""
    def __init__(self):
        self.requests = []
    def supports_tools(self, model): return True
    async def chat(self, messages, model, tools=None, **kw):
        self.requests.append({"tools": [t["function"]["name"] for t in (tools or [])],
                              "system": messages[0]["content"] if messages else ""})
        if len(self.requests) == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "s1", "type": "function",
                 "function": {"name": "grep_files",
                              "arguments": json.dumps({"pattern": "COMPACTION_TRIGGER", "path": "src"})}}]},
                "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"role": "assistant",
                             "content": "Found: COMPACTION_TRIGGER_TOKENS = 12000 at src/clio/agent/compaction.py:23"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


class TestRunSubagent:
    def test_full_dispatch_roundtrip(self):
        parent = make_parent(ScriptedSubProvider())
        result = asyncio.run(run_subagent(parent, "find the compaction trigger constant"))
        assert "COMPACTION_TRIGGER_TOKENS = 12000" in result
        # sub-agent ran with the restricted toolset and its own prompt
        req = parent.provider.requests[0]
        assert set(req["tools"]) == SUBAGENT_ALLOWED_TOOLS
        assert "dispatch_agent" not in req["tools"]
        assert SUBAGENT_SYSTEM_PROMPT.splitlines()[0] in req["system"]
        # parent history untouched by the sub-agent's internal turns
        assert parent.messages == []

    def test_usage_forwarded_to_parent_ledger(self):
        parent = make_parent(ScriptedSubProvider())
        asyncio.run(run_subagent(parent, "task"))
        rows = parent.history_db.usage_rows
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == 7

    def test_empty_task_rejected_without_llm_call(self):
        parent = make_parent(ScriptedSubProvider())
        result = asyncio.run(run_subagent(parent, "  "))
        assert result.startswith("Error:")
        assert parent.provider.requests == []

    def test_timeout_returns_bounded_error(self, monkeypatch):
        class SlowProvider:
            def supports_tools(self, model): return True
            async def chat(self, *a, **k):
                await asyncio.sleep(5)
        monkeypatch.setattr("clio.agent.subagent.SUBAGENT_TIMEOUT_SECONDS", 0.2)
        parent = make_parent(SlowProvider())
        result = asyncio.run(run_subagent(parent, "task"))
        assert "timed out" in result

    def test_turn_cap_applies(self):
        class LoopingProvider:
            def __init__(self): self.n = 0
            def supports_tools(self, model): return True
            async def chat(self, messages, model, tools=None, **kw):
                self.n += 1
                return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": f"c{self.n}", "type": "function",
                     "function": {"name": "list_directory", "arguments": json.dumps({"path": f"d{self.n}"})}}]},
                    "finish_reason": "tool_calls"}]}
        parent = make_parent(LoopingProvider())
        result = asyncio.run(run_subagent(parent, "task"))
        assert "Max turns reached" in result
        from clio.agent.subagent import SUBAGENT_MAX_TURNS
        assert parent.provider.n == SUBAGENT_MAX_TURNS


class TestParentIntegration:
    def test_parent_dispatches_and_gets_report(self):
        class ParentProvider:
            def __init__(self): self.n = 0; self.first_tools = None
            def supports_tools(self, model): return True
            async def chat(self, messages, model, tools=None, **kw):
                self.n += 1
                if self.n == 1:
                    self.first_tools = [t["function"]["name"] for t in (tools or [])]
                    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "p1", "type": "function",
                         "function": {"name": "dispatch_agent",
                                      "arguments": json.dumps({"task": "research X"})}}]},
                        "finish_reason": "tool_calls"}]}
                if self.n == 2:  # this is the SUB-agent's one and only call
                    return {"choices": [{"message": {"role": "assistant", "content": "sub-report: X lives in y.py:9"},
                                         "finish_reason": "stop"}]}
                # parent resumes with the report in context
                report = next(m["content"] for m in messages if m.get("role") == "tool")
                return {"choices": [{"message": {"role": "assistant",
                                     "content": f"Answer based on: {report}"}, "finish_reason": "stop"}]}
        parent = make_parent(ParentProvider())
        result = asyncio.run(parent.chat("where does X live?"))
        assert "sub-report: X lives in y.py:9" in result
        assert "dispatch_agent" in parent.provider.first_tools

    def test_subagent_cannot_recurse(self):
        parent = make_parent(ScriptedSubProvider())
        from clio.agent.subagent import _make_subagent
        sub = _make_subagent(parent)
        assert sub.allow_subagents is False
        # its Tools reject dispatch outright
        result = asyncio.run(sub.tools.execute_tool("dispatch_agent", {"task": "x"}))
        assert "not available" in result
        # and its definitions don't include it
        names = [d["function"]["name"] for d in sub.tools.get_tool_definitions()]
        assert "dispatch_agent" not in names
        assert set(names) == SUBAGENT_ALLOWED_TOOLS

    def test_restricted_tools_reject_writes(self):
        tools = Tools(allowed_tools=set(SUBAGENT_ALLOWED_TOOLS))
        result = asyncio.run(tools.execute_tool("write_file", {"path": "x", "content": "y"}))
        assert "not available" in result
        result = asyncio.run(tools.execute_tool("execute_bash", {"command": "rm -rf /tmp/x"}))
        assert "not available" in result


class TestDefinition:
    def test_definition_shape(self):
        fn = DISPATCH_AGENT_DEFINITION["function"]
        assert fn["name"] == "dispatch_agent"
        assert fn["parameters"]["required"] == ["task"]
