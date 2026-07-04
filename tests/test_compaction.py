"""Unit tests for context compaction helpers."""

import pytest

from clio.agent.compaction import (
    SUMMARY_MARKER,
    apply_window,
    build_compacted_history,
    estimate_tokens,
    find_split_point,
    is_summary_message,
    truncate_old_tool_outputs,
)


def user(content):
    return {"role": "user", "content": content}


def assistant(content, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def tool(content, call_id="c1"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


class TestFindSplitPoint:
    def test_splits_at_user_message(self):
        messages = [
            user("x" * 1000),
            assistant("y" * 1000),
            user("z" * 100),
            assistant("w" * 100),
        ]
        split = find_split_point(messages, compress_fraction=0.7)
        assert split == 2
        assert messages[split]["role"] == "user"

    def test_never_splits_between_tool_call_and_result(self):
        tc = [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]
        messages = [
            user("a" * 500),
            assistant(None, tool_calls=tc),
            tool("b" * 5000),
            assistant("done"),
            user("next"),
            assistant("ok"),
        ]
        split = find_split_point(messages, compress_fraction=0.5)
        # Only valid split points are user-message indices (0 or 4) or len.
        assert split in (0, 4, len(messages))
        assert split != 2 and split != 3

    def test_compress_everything_when_history_ends_with_plain_assistant(self):
        messages = [user("a" * 100), assistant("b" * 100)]
        split = find_split_point(messages, compress_fraction=0.9)
        assert split == len(messages)

    def test_empty_history(self):
        assert find_split_point([]) == 0

    def test_invalid_fraction_raises(self):
        with pytest.raises(ValueError):
            find_split_point([user("a")], compress_fraction=1.5)


class TestTruncateOldToolOutputs:
    def test_newest_outputs_kept_oldest_truncated(self):
        old_output = "\n".join(f"old line {i}" for i in range(500))
        new_output = "\n".join(f"new line {i}" for i in range(500))
        messages = [
            user("q1"),
            tool(old_output),
            user("q2"),
            tool(new_output),
        ]
        result = truncate_old_tool_outputs(messages, budget_chars=len(new_output) + 10)
        assert result[3]["content"] == new_output  # newest kept in full
        assert "truncated during compaction" in result[1]["content"]
        assert "old line 499" in result[1]["content"]  # last lines kept
        assert "old line 0" not in result[1]["content"]

    def test_small_outputs_never_truncated(self):
        messages = [tool("small"), tool("also small")]
        result = truncate_old_tool_outputs(messages, budget_chars=1)
        assert result[0]["content"] == "small"
        assert result[1]["content"] == "also small"

    def test_originals_not_mutated(self):
        big = "x\n" * 5000
        messages = [tool(big), tool(big)]
        truncate_old_tool_outputs(messages, budget_chars=100)
        assert messages[0]["content"] == big


class TestCompactedHistory:
    def test_build_and_detect_summary(self):
        tail = [user("recent"), assistant("reply")]
        history = build_compacted_history("<state_snapshot>...</state_snapshot>", tail)
        assert len(history) == 4
        assert is_summary_message(history[0])
        assert history[0]["content"].startswith(SUMMARY_MARKER)
        assert history[1]["role"] == "assistant"
        assert history[2:] == tail

    def test_plain_user_message_is_not_summary(self):
        assert not is_summary_message(user("hello"))
        assert not is_summary_message(assistant(SUMMARY_MARKER))


class TestApplyWindow:
    def test_no_trim_when_under_limit(self):
        messages = [user("a"), assistant("b")]
        assert apply_window(messages, 10) == messages

    def test_plain_window_drops_oldest(self):
        messages = [user(str(i)) for i in range(30)]
        result = apply_window(messages, 20)
        assert len(result) == 20
        assert result[0]["content"] == "10"

    def test_summary_pair_preserved(self):
        history = build_compacted_history("<state_snapshot/>", [])
        history += [user(str(i)) for i in range(30)]
        result = apply_window(history, 20)
        assert is_summary_message(result[0])
        assert len(result) == 22  # summary pair + 20-message tail
        assert result[-1]["content"] == "29"


class TestEstimateTokens:
    def test_counts_grow_with_content(self):
        small = estimate_tokens([user("hi")])
        large = estimate_tokens([user("hello world " * 1000)])
        assert large > small > 0

    def test_handles_none_content_and_tool_calls(self):
        tc = [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]
        assert estimate_tokens([assistant(None, tool_calls=tc)]) > 0
