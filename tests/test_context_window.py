"""Unit tests for context window resolution."""

import asyncio

from clio.agent.context_window import (
    DEFAULT_CONTEXT_WINDOW,
    _ollama_root,
    get_context_window,
    lookup_known_window,
)


class TestLookupKnownWindow:
    def test_exact_family_prefix(self):
        assert lookup_known_window("qwen3-coder-unsloth:30b") == 262144
        assert lookup_known_window("devstral-small-2:24b") == 131072
        assert lookup_known_window("llama3.1:8b") == 131072

    def test_specific_prefix_beats_general(self):
        assert lookup_known_window("qwen3:8b") == 40960
        assert lookup_known_window("qwen3-coder:30b") == 262144

    def test_namespace_prefix_stripped(self):
        assert lookup_known_window("unsloth/qwen3-coder:30b") == 262144

    def test_unknown_model(self):
        assert lookup_known_window("totally-novel-model:7b") is None

    def test_case_insensitive(self):
        assert lookup_known_window("Claude-Sonnet") == 200000


class TestOllamaRoot:
    def test_strips_v1_suffix(self):
        assert _ollama_root("http://localhost:11434/v1") == "http://localhost:11434"

    def test_plain_root_kept(self):
        assert _ollama_root("http://localhost:11434") == "http://localhost:11434"

    def test_empty(self):
        assert _ollama_root("") is None


class TestGetContextWindow:
    def test_override_wins(self):
        result = asyncio.run(get_context_window(
            "qwen3-coder:30b", base_url="http://localhost:1/v1", override=65536
        ))
        assert result == 65536

    def test_falls_back_to_known_table_when_server_unreachable(self):
        result = asyncio.run(get_context_window(
            "devstral-small-2:24b", base_url="http://localhost:1/v1"
        ))
        assert result == 131072

    def test_default_when_nothing_known(self):
        result = asyncio.run(get_context_window("mystery-model:1b"))
        assert result == DEFAULT_CONTEXT_WINDOW
