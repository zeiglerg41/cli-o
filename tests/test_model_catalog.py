"""Unit tests for dynamic model capability resolution."""

import asyncio
import json

import httpx

from clio.providers.model_catalog import (
    ToolSupport,
    is_tool_rejection_error,
    query_anthropic_model,
    query_ollama_capabilities,
    resolve_tool_support,
)


def ollama_transport(capabilities=None, status=200):
    def handler(request):
        assert request.url.path == "/api/show"
        body = {"capabilities": capabilities} if capabilities is not None else {}
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def anthropic_transport(status=200, body=None):
    def handler(request):
        assert request.url.path.startswith("/v1/models/")
        assert request.headers.get("x-api-key")
        return httpx.Response(status, json=body or {})
    return httpx.MockTransport(handler)


def run(coro):
    return asyncio.run(coro)


class TestOllamaResolution:
    def test_tools_capability_present(self):
        ts = run(resolve_tool_support(
            "openai-compatible", "somemodel:7b",
            base_url="http://localhost:11434/v1",
            transport=ollama_transport(["completion", "tools", "thinking"]),
        ))
        assert ts == ToolSupport(True, "ollama")

    def test_tools_capability_absent_is_authoritative_no(self):
        ts = run(resolve_tool_support(
            "openai-compatible", "textonly:3b",
            base_url="http://localhost:11434/v1",
            transport=ollama_transport(["completion"]),
        ))
        assert ts == ToolSupport(False, "ollama")

    def test_server_without_capabilities_field_falls_through(self):
        # Older Ollama or non-Ollama openai-compatible server: no signal,
        # must NOT be treated as a no — falls to static/assumed.
        ts = run(resolve_tool_support(
            "openai-compatible", "gpt-4o",
            base_url="http://some-openai-proxy/v1",
            transport=ollama_transport(capabilities=None),
        ))
        assert ts.supported is True
        assert ts.source in ("static", "assumed")


class TestAnthropicResolution:
    def test_existing_model_supports_tools(self):
        ts = run(resolve_tool_support(
            "anthropic", "claude-fable-5", api_key="sk-test",
            transport=anthropic_transport(200, {"id": "claude-fable-5", "max_input_tokens": 1000000}),
        ))
        assert ts == ToolSupport(True, "anthropic-api")

    def test_unknown_model_404(self):
        ts = run(resolve_tool_support(
            "anthropic", "claude-nonexistent", api_key="sk-test",
            transport=anthropic_transport(404, {"type": "error"}),
        ))
        assert ts == ToolSupport(False, "anthropic-api")

    def test_no_api_key_falls_to_static_matrix(self):
        ts = run(resolve_tool_support("anthropic", "claude-fable-5", api_key=None))
        assert ts == ToolSupport(True, "static")

    def test_server_error_falls_through_not_denied(self):
        ts = run(resolve_tool_support(
            "anthropic", "claude-fable-5", api_key="sk-test",
            transport=anthropic_transport(500),
        ))
        assert ts.supported is True  # static fallback, never deny on outage

    def test_context_window_from_models_api(self):
        info = run(query_anthropic_model(
            "claude-fable-5", "sk-test",
            transport=anthropic_transport(200, {"max_input_tokens": 1000000}),
        ))
        assert info["max_input_tokens"] == 1000000


class TestAllowByDefault:
    def test_unknown_model_unknown_provider_assumed_true(self):
        ts = run(resolve_tool_support("openai-compatible", "brand-new-model-2027"))
        assert ts == ToolSupport(True, "assumed")

    def test_static_matrix_still_consulted(self):
        ts = run(resolve_tool_support("openai", "gpt-4o"))
        assert ts == ToolSupport(True, "static")


class TestToolRejectionDetector:
    def test_real_ollama_rejection(self):
        assert is_tool_rejection_error(
            'registry.ollama.ai/library/gemma2:2b does not support tools'
        )

    def test_openai_style_rejection(self):
        assert is_tool_rejection_error(
            "400: tool use is not supported for this model"
        )
        assert is_tool_rejection_error("Tools are not supported by this endpoint")

    def test_tool_execution_failures_do_not_match(self):
        assert not is_tool_rejection_error("Error: Unknown tool: read_flie")
        assert not is_tool_rejection_error("tool call failed: file not found")
        assert not is_tool_rejection_error("429 rate_limit_exceeded")
        assert not is_tool_rejection_error("")
        assert not is_tool_rejection_error(None)
