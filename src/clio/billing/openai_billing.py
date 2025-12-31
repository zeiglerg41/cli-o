"""OpenAI billing API integration."""
import httpx
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List


def _normalize_model_name(line_item: str) -> str:
    """Normalize OpenAI billing line_item to base model name.

    Converts 'gpt-4.1-2025-04-14, cached input' -> 'gpt-4.1'
    Converts 'gpt-5.2-2025-12-11, output' -> 'gpt-5.2'

    Args:
        line_item: Line item from OpenAI billing API

    Returns:
        Normalized base model name
    """
    # Remove token type suffix (e.g., ", cached input", ", input", ", output")
    base = line_item.split(',')[0].strip()

    # Remove date suffix (format: -YYYY-MM-DD)
    # Match pattern like -2025-04-14 at the end
    base = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', base)

    return base


def fetch_openai_costs(
    admin_api_key: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, float]:
    """Fetch actual costs from OpenAI's billing API.

    Args:
        admin_api_key: Admin API key (sk-proj-... with admin permissions)
        start_date: Start date for cost query (defaults to start of current month)
        end_date: End date for cost query (defaults to now)

    Returns:
        Dict mapping model names to actual USD costs

    Raises:
        httpx.HTTPError: If API request fails
    """
    # Default to current month
    if start_date is None:
        now = datetime.now()
        start_date = datetime(now.year, now.month, 1)
    if end_date is None:
        end_date = datetime.now()

    # Convert to Unix timestamps
    start_time = int(start_date.timestamp())
    end_time = int(end_date.timestamp())

    # OpenAI Costs API endpoint
    url = "https://api.openai.com/v1/organization/costs"

    headers = {
        "Authorization": f"Bearer {admin_api_key}",
        "Content-Type": "application/json",
    }

    params = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": "1d",  # Daily buckets
        "group_by": ["line_item"],  # Group by model/service
    }

    costs_by_model = {}

    with httpx.Client(timeout=30.0) as client:
        # Handle pagination - keep fetching until has_more is False
        page_count = 0
        max_pages = 10  # Safety limit

        while page_count < max_pages:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            # Parse costs from this page
            if "data" in data:
                for bucket in data["data"]:
                    if "results" in bucket:
                        for result in bucket["results"]:
                            # line_item contains the model name with date and token type
                            line_item = result.get("line_item", "unknown")
                            # Normalize to base model name (e.g., "gpt-4.1-2025-04-14, input" -> "gpt-4.1")
                            model = _normalize_model_name(line_item)

                            amount_obj = result.get("amount", {})

                            # Extract value from amount dict
                            if isinstance(amount_obj, dict):
                                amount = float(amount_obj.get("value", 0.0))
                            else:
                                amount = float(amount_obj)

                            # Aggregate costs by base model name
                            if model in costs_by_model:
                                costs_by_model[model] += amount
                            else:
                                costs_by_model[model] = amount

            # Check if there are more pages
            if not data.get("has_more", False):
                break

            # Get next page cursor
            next_page = data.get("next_page")
            if not next_page:
                break

            # Update params for next page
            params["page"] = next_page
            page_count += 1

    return costs_by_model


def fetch_openai_usage(
    admin_api_key: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[Dict]:
    """Fetch token usage from OpenAI's usage API.

    Args:
        admin_api_key: Admin API key
        start_date: Start date (defaults to start of current month)
        end_date: End date (defaults to now)

    Returns:
        List of usage records with model, tokens, and costs
    """
    # Default to current month
    if start_date is None:
        now = datetime.now()
        start_date = datetime(now.year, now.month, 1)
    if end_date is None:
        end_date = datetime.now()

    start_time = int(start_date.timestamp())
    end_time = int(end_date.timestamp())

    url = "https://api.openai.com/v1/organization/usage/completions"

    headers = {
        "Authorization": f"Bearer {admin_api_key}",
        "Content-Type": "application/json",
    }

    params = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": "1d",
        "group_by": ["model"],
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

    # Parse usage by model
    usage_by_model = {}

    if "data" in data:
        for bucket in data["data"]:
            if "results" in bucket:
                for result in bucket["results"]:
                    model = result.get("model") or result.get("line_item", "unknown")
                    input_tokens = result.get("input_tokens", 0)
                    output_tokens = result.get("output_tokens", 0)

                    if model in usage_by_model:
                        usage_by_model[model]["input_tokens"] += input_tokens
                        usage_by_model[model]["output_tokens"] += output_tokens
                    else:
                        usage_by_model[model] = {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        }

    return usage_by_model
