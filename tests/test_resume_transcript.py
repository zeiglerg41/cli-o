"""Unit tests for the --continue transcript replay."""

import io

from rich.console import Console

from clio.agent.compaction import SUMMARY_ACK, SUMMARY_MARKER
from clio.cli_repl import ClioREPL


class FakeDB:
    def get_conversation(self, cid):
        return {"title": "auth refactor"}


class FakeAgent:
    def __init__(self, messages):
        self.messages = messages
        self.conversation_id = 7
        self.history_db = FakeDB()


def render(messages):
    repl = object.__new__(ClioREPL)
    buf = io.StringIO()
    repl.console = Console(file=buf, highlight=False, width=200)
    repl.username = "gare"
    repl.agent = FakeAgent(messages)
    repl._print_resume_transcript()
    return buf.getvalue()


class TestResumeTranscript:
    def test_renders_user_and_assistant_turns(self):
        out = render([
            {"role": "user", "content": "rename login to sign_in"},
            {"role": "assistant", "content": "Renamed in src/auth.py."},
        ])
        assert "gare › rename login to sign_in" in out
        assert "clio › Renamed in src/auth.py." in out
        assert "resuming conversation #7 · auth refactor" in out
        assert "end of history" in out

    def test_tool_calls_shown_dim_results_skipped(self):
        out = render([
            {"role": "user", "content": "check the tests"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "function": {"name": "execute_bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "500 lines of pytest output"},
            {"role": "assistant", "content": "All tests pass."},
        ])
        assert "→ execute_bash" in out
        assert "500 lines of pytest output" not in out
        assert "clio › All tests pass." in out

    def test_compaction_snapshot_collapsed(self):
        out = render([
            {"role": "user", "content": f"{SUMMARY_MARKER}\n\n<state_snapshot>secret details</state_snapshot>"},
            {"role": "assistant", "content": SUMMARY_ACK},
            {"role": "user", "content": "keep going"},
        ])
        assert "compacted into a snapshot" in out
        assert "secret details" not in out
        assert SUMMARY_ACK not in out
        assert "gare › keep going" in out

    def test_thinking_tags_stripped(self):
        out = render([
            {"role": "assistant", "content": "<think>internal reasoning</think>The answer is 4."},
        ])
        assert "internal reasoning" not in out
        assert "clio › The answer is 4." in out

    def test_empty_history_prints_nothing(self):
        assert render([]) == ""
