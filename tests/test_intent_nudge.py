"""Unit tests for the unfinished-intent detector, including the long-message gap."""

from clio.agent.core import _looks_like_unfinished_intent


class TestFires:
    def test_trailing_colon(self):
        assert _looks_like_unfinished_intent("Let me search more broadly:")

    def test_short_intent_message(self):
        assert _looks_like_unfinished_intent("I'll check the config file next.")

    def test_long_message_ending_with_announced_action(self):
        # The live stall observed from qwen3-coder: a long analysis that ends
        # by announcing an action it never takes.
        long_analysis = (
            "Based on my analysis of the clio project, the team has made significant "
            "progress on context management with features like compaction and plan "
            "tools. The core.py file handles session logging and memory management, "
            "and the tools module already implements render_plan and update_plan. "
            "However there is still room for improvement in task tracking. "
            "Let me look into this a bit more by checking what storage mechanisms "
            "are already in place."
        )
        assert len(long_analysis) > 240  # confirms the old gate would have skipped it
        assert _looks_like_unfinished_intent(long_analysis)


class TestDoesNotFire:
    def test_complete_answer(self):
        assert not _looks_like_unfinished_intent(
            "The function is defined in src/main.py at line 40."
        )

    def test_long_answer_mentioning_intent_mid_message(self):
        text = (
            "I checked the three files you mentioned. First I thought let me search "
            "the tests too, which I did, and they all pass. The change you asked "
            "about was introduced in commit abc123 and only affects the parser. "
            "No other modules import it, so the refactor is safe to apply as-is. "
            "The behavior difference you saw comes from the new default argument. "
            "Everything else in the module is unchanged from the previous release."
        )
        assert len(text) > 240
        assert not _looks_like_unfinished_intent(text)

    def test_closing_pleasantry_excluded(self):
        text = (
            "The refactor is complete and all the tests pass without errors. "
            "The parser now handles both formats and the config loads correctly. "
            "I verified the output matches the expected values in all three cases "
            "and updated the documentation accordingly for the new behavior. "
            "Everything is committed on the feature branch as you requested. "
            "Let me know if you want anything else."
        )
        assert len(text) > 240
        assert not _looks_like_unfinished_intent(text)

    def test_empty(self):
        assert not _looks_like_unfinished_intent("")
        assert not _looks_like_unfinished_intent(None)
