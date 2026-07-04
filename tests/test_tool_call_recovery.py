"""Unit tests for text-embedded tool call recovery."""

import json

from clio.agent.tool_call_recovery import extract_text_tool_calls, to_structured_tool_calls

KNOWN = {"execute_bash", "read_file", "grep_files", "update_plan"}


class TestExtraction:
    def test_observed_live_format(self):
        # Exactly what qwen3-coder emitted in the live session: bare JSON
        # followed by a stray closing tag.
        content = (
            "I'll investigate the git status to see what files would be committed.\n\n"
            '{"name": "execute_bash", "arguments": {"command": "git status --porcelain"}}\n'
            "</tool_call>"
        )
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [{"name": "execute_bash", "arguments": {"command": "git status --porcelain"}}]
        assert cleaned == "I'll investigate the git status to see what files would be committed."
        assert "</tool_call>" not in cleaned

    def test_hermes_tagged_block(self):
        content = '<tool_call>\n{"name": "read_file", "arguments": {"path": "a.py"}}\n</tool_call>'
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [{"name": "read_file", "arguments": {"path": "a.py"}}]
        assert cleaned == ""

    def test_json_fenced_block(self):
        content = 'Let me check.\n```json\n{"name": "grep_files", "arguments": {"pattern": "def main"}}\n```'
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [{"name": "grep_files", "arguments": {"pattern": "def main"}}]
        assert cleaned == "Let me check."

    def test_multiple_calls(self):
        content = (
            '{"name": "read_file", "arguments": {"path": "a.py"}}\n'
            '{"name": "read_file", "arguments": {"path": "b.py"}}'
        )
        _, calls = extract_text_tool_calls(content, KNOWN)
        assert [c["arguments"]["path"] for c in calls] == ["a.py", "b.py"]

    def test_missing_arguments_defaults_to_empty(self):
        content = '{"name": "execute_bash"}'
        _, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [{"name": "execute_bash", "arguments": {}}]

    def test_nested_json_in_arguments(self):
        content = '{"name": "update_plan", "arguments": {"plan": [{"step": "a", "status": "pending"}]}}'
        _, calls = extract_text_tool_calls(content, KNOWN)
        assert calls[0]["arguments"]["plan"][0]["step"] == "a"


class TestNoFalsePositives:
    def test_plain_text_untouched(self):
        content = "The function is defined in src/main.py at line 40."
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [] and cleaned == content

    def test_unknown_tool_name_left_alone(self):
        content = '{"name": "delete_everything", "arguments": {}}'
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [] and cleaned == content

    def test_json_about_a_name_key_not_a_tool(self):
        # Model legitimately discussing JSON with a "name" field
        content = 'Your config should look like: {"name": "my-provider", "type": "openai"}'
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [] and cleaned == content

    def test_invalid_json_left_alone(self):
        content = '{"name": "execute_bash", "arguments": {"command": unquoted}}'
        cleaned, calls = extract_text_tool_calls(content, KNOWN)
        assert calls == [] and cleaned == content

    def test_empty_and_none(self):
        assert extract_text_tool_calls("", KNOWN) == ("", [])
        assert extract_text_tool_calls(None, KNOWN) == (None, [])


class TestToStructured:
    def test_openai_format(self):
        calls = [{"name": "execute_bash", "arguments": {"command": "ls"}}]
        structured = to_structured_tool_calls(calls, "recovered_t3")
        assert structured[0]["id"] == "recovered_t3_0"
        assert structured[0]["type"] == "function"
        assert structured[0]["function"]["name"] == "execute_bash"
        assert json.loads(structured[0]["function"]["arguments"]) == {"command": "ls"}
