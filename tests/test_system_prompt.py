"""Guardrail tests: the system prompt keeps its critical operating sections."""

from clio.agent.constants import DEFAULT_SYSTEM_PROMPT


class TestSystemPromptSections:
    def test_git_workflow_guidance_present(self):
        assert "GIT WORKFLOWS:" in DEFAULT_SYSTEM_PROMPT
        assert "git ls-remote origin" in DEFAULT_SYSTEM_PROMPT
        assert "NEWEST FIRST" in DEFAULT_SYSTEM_PROMPT
        assert "reset --hard" in DEFAULT_SYSTEM_PROMPT

    def test_capability_manifest_present(self):
        assert "NEVER CLAIM YOU LACK THEM" in DEFAULT_SYSTEM_PROMPT
        assert "git add/commit/push" in DEFAULT_SYSTEM_PROMPT

    def test_grounding_rules_present(self):
        assert "GROUNDING" in DEFAULT_SYSTEM_PROMPT

    def test_all_tools_listed(self):
        for tool in ["execute_bash", "read_file", "edit_file", "update_plan", "grep_files"]:
            assert tool in DEFAULT_SYSTEM_PROMPT
