"""Unit tests for usage/cost tracking: pricing chain, DB ledger, stream capture."""

import asyncio
import json

import httpx

from clio.providers.pricing import (
    CostInfo,
    fetch_openrouter_pricing,
    resolve_cost,
)
from clio.history.database import HistoryDatabase


STATIC = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


class TestResolveCost:
    def test_billed_wins_over_everything(self):
        # Shape verified live against OpenRouter usage accounting
        usage = {"prompt_tokens": 6, "completion_tokens": 5, "cost": 1.19712e-05}
        info = resolve_cost("deepseek/deepseek-v4-pro", 6, 5,
                            response_usage=usage,
                            live_pricing={"deepseek/deepseek-v4-pro": (1.0, 1.0)},
                            static_pricing=STATIC)
        assert info == CostInfo(1.19712e-05, "billed")

    def test_live_pricing_when_no_billed_cost(self):
        info = resolve_cost("deepseek/deepseek-v4-pro", 1000, 500,
                            response_usage={"prompt_tokens": 1000},
                            live_pricing={"deepseek/deepseek-v4-pro": (1e-6, 2e-6)})
        assert info.source == "computed"
        assert abs(info.cost_usd - (1000 * 1e-6 + 500 * 2e-6)) < 1e-12

    def test_static_estimate_with_prefix_match(self):
        info = resolve_cost("claude-opus-4-8-latest", 1_000_000, 0,
                            static_pricing=STATIC)
        assert info == CostInfo(5.00, "estimate")

    def test_unknown_is_tagged_not_silent_zero(self):
        info = resolve_cost("brand-new-model", 5000, 100)
        assert info.cost_usd == 0.0
        assert info.source == "unknown"

    def test_non_numeric_cost_field_ignored(self):
        info = resolve_cost("m", 10, 10, response_usage={"cost": "n/a"},
                            static_pricing=STATIC)
        assert info.source == "unknown"

    def test_local_endpoint_is_free_not_unknown(self):
        from clio.providers.pricing import is_local_endpoint
        assert is_local_endpoint("http://localhost:11434/v1")
        assert not is_local_endpoint("https://openrouter.ai/api/v1")
        info = resolve_cost("qwen3:30b-a3b", 5000, 200, is_local=True)
        assert info == CostInfo(0.0, "local")


class TestOpenRouterCatalogParse:
    def test_parses_pricing(self):
        def handler(request):
            return httpx.Response(200, json={"data": [
                {"id": "a/model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
                {"id": "b/broken", "pricing": {"prompt": None}},
            ]})
        pricing = asyncio.run(fetch_openrouter_pricing(transport=httpx.MockTransport(handler)))
        assert pricing["a/model"] == (1e-06, 2e-06)
        assert "b/broken" not in pricing

    def test_server_error_returns_none(self):
        def handler(request):
            return httpx.Response(500)
        assert asyncio.run(fetch_openrouter_pricing(transport=httpx.MockTransport(handler))) is None


class TestLedger:
    def test_cost_source_roundtrip_and_monthly_rollup(self, tmp_path):
        db = HistoryDatabase(db_path=tmp_path / "u.db")
        cid = db.create_conversation("/tmp", "m", "p")
        db.add_usage_stat(cid, "deepseek/deepseek-v4-pro", "openrouter", 100, 50, 0.001, cost_source="billed")
        db.add_usage_stat(cid, "deepseek/deepseek-v4-pro", "openrouter", 200, 80, 0.002, cost_source="billed")
        db.add_usage_stat(cid, "mystery:1b", "local-gpu", 500, 100, 0.0, cost_source="unknown")
        rows = db.get_monthly_usage()
        by_model = {r["model"]: r for r in rows}
        ds = by_model["deepseek/deepseek-v4-pro"]
        assert ds["provider"] == "openrouter"
        assert ds["prompt_tokens"] == 300 and ds["completion_tokens"] == 130
        assert not ds["has_estimates"] and ds["unknown_rows"] == 0
        my = by_model["mystery:1b"]
        assert my["has_estimates"] and my["unknown_rows"] == 1
        db.close()

    def test_default_source_is_estimate(self, tmp_path):
        db = HistoryDatabase(db_path=tmp_path / "u.db")
        cid = db.create_conversation("/tmp", "m", "p")
        db.add_usage_stat(cid, "gpt-4o", "openai", 10, 5, 0.01)
        assert db.get_monthly_usage()[0]["has_estimates"] is True
        db.close()

    def test_migration_on_existing_db(self, tmp_path):
        db = HistoryDatabase(db_path=tmp_path / "u.db")
        db.close()
        db = HistoryDatabase(db_path=tmp_path / "u.db")  # re-open runs migrations again
        cid = db.create_conversation("/tmp", "m", "p")
        db.add_usage_stat(cid, "m", "p", 1, 1, 0.0, cost_source="billed")
        db.close()


class TestStreamingUsageCapture:
    def test_usage_chunk_with_empty_choices_is_captured(self):
        from clio.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider({"base_url": "http://localhost:1/v1", "api_key": "x"})

        async def fake_stream(messages, model, tools=None, **kw):
            yield {"id": "1", "choices": [{"delta": {"content": "hel"}, "finish_reason": None}]}
            yield {"id": "2", "choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]}
            # final usage chunk: EMPTY choices — the shape include_usage sends
            yield {"id": "3", "choices": [],
                   "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14, "cost": 0.0001}}

        provider.stream_chat = fake_stream
        result = asyncio.run(provider.chat_streaming([], "m"))
        assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 2,
                                   "total_tokens": 14, "cost": 0.0001}
        assert result["choices"][0]["message"]["content"] == "hello"

    def test_usage_dict_preserves_cost_extra(self):
        from clio.providers.openai_compatible import OpenAICompatibleProvider
        out = OpenAICompatibleProvider._usage_dict(
            {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8, "cost": 2e-05, "is_byok": False}
        )
        assert out == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8, "cost": 2e-05}

    def test_usage_dict_none(self):
        from clio.providers.openai_compatible import OpenAICompatibleProvider
        assert OpenAICompatibleProvider._usage_dict(None) is None
