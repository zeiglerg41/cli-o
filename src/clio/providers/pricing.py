"""Cost resolution for usage tracking.

Resolution order per request (most authoritative first):

1. "billed"   — the provider reported the exact charged cost in the response.
                OpenRouter does this when usage accounting is requested
                (verified live: usage.cost carries dollars).
2. "computed" — tokens x live-fetched per-token pricing (OpenRouter /models
                publishes pricing for every model it serves; cached with TTL).
3. "estimate" — tokens x the static price table (prefix-matched). Rots as
                models launch, so it is a labeled fallback, never silent truth.
4. "unknown"  — nothing matched. Cost recorded as 0.0 but TAGGED unknown so
                a spend report can say "N requests had unpriceable models"
                instead of quietly under-reporting.
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_PRICING_TTL_SECONDS = 3600


@dataclass
class CostInfo:
    cost_usd: float
    source: str  # "billed" | "computed" | "estimate" | "unknown"


# module-level TTL cache: {"at": timestamp, "pricing": {model_id: (in, out)}}
_openrouter_cache: dict = {}


async def fetch_openrouter_pricing(
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[Dict[str, Tuple[float, float]]]:
    """Live per-token pricing (USD) for every OpenRouter model, or None."""
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
            if resp.status_code != 200:
                return None
            out = {}
            for m in resp.json().get("data", []):
                p = m.get("pricing") or {}
                try:
                    out[m["id"]] = (float(p.get("prompt", 0)), float(p.get("completion", 0)))
                except (TypeError, ValueError):
                    continue
            return out or None
    except Exception:
        return None


async def get_live_pricing(
    base_url: Optional[str],
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[Dict[str, Tuple[float, float]]]:
    """Live pricing catalog for the provider, if it publishes one (TTL-cached)."""
    if not base_url or "openrouter" not in base_url:
        return None
    now = time.time()
    if _openrouter_cache and now - _openrouter_cache.get("at", 0) < _PRICING_TTL_SECONDS:
        return _openrouter_cache.get("pricing")
    pricing = await fetch_openrouter_pricing(transport=transport)
    if pricing:
        _openrouter_cache["at"] = now
        _openrouter_cache["pricing"] = pricing
    return pricing


def _static_lookup(model: str, static_pricing: Optional[dict]) -> Optional[dict]:
    """Prefix-matched lookup in the static table (same semantics as the old
    Agent._calculate_cost)."""
    if not static_pricing:
        return None
    low = model.lower()
    if low in static_pricing:
        return static_pricing[low]
    for prefix, p in static_pricing.items():
        if low.startswith(prefix):
            return p
    return None


def is_local_endpoint(base_url: Optional[str]) -> bool:
    """True for self-hosted endpoints where inference is genuinely free."""
    if not base_url:
        return False
    return any(h in base_url for h in ("localhost", "127.0.0.1", "0.0.0.0"))


def resolve_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    response_usage: Optional[dict] = None,
    live_pricing: Optional[Dict[str, Tuple[float, float]]] = None,
    static_pricing: Optional[dict] = None,
    is_local: bool = False,
) -> CostInfo:
    """Resolve the cost of one request (see module docstring for the order)."""
    # 0. Self-hosted: genuinely free, not "unpriceable"
    if is_local:
        return CostInfo(0.0, "local")

    # 1. Provider-reported billed cost
    if response_usage and isinstance(response_usage.get("cost"), (int, float)):
        return CostInfo(float(response_usage["cost"]), "billed")

    # 2. Live per-token pricing
    if live_pricing and model in live_pricing:
        p_in, p_out = live_pricing[model]
        return CostInfo(prompt_tokens * p_in + completion_tokens * p_out, "computed")

    # 3. Static table (per-million prices, as in the legacy table)
    static = _static_lookup(model, static_pricing)
    if static is not None:
        cost = (
            prompt_tokens * static.get("input", 0) / 1_000_000
            + completion_tokens * static.get("output", 0) / 1_000_000
        )
        return CostInfo(cost, "estimate")

    # 4. Unpriceable — tagged, never a silent $0 "fact"
    return CostInfo(0.0, "unknown")
