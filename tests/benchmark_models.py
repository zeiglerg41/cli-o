#!/usr/bin/env python3
"""
Model Benchmark Script for CLIO

Tests all available models on OpenWebUI for:
1. Response time (speed)
2. Tool calling accuracy
3. Context understanding
4. Code generation quality

Usage:
    python tests/benchmark_models.py
"""

import asyncio
import time
import json
from pathlib import Path
from typing import Dict, List, Any
import httpx


# Configuration
API_BASE_URL = "https://open-webui-remote-1.tech/api"
API_KEY = "sk-6488eea7cae54966b0560de66de6a9aa"

# Models to test (from your config)
MODELS = [
    "llama3.1:8b",
    "qwen2.5:7b",
    "qwen2.5:3b",
    "mistral:7b",
    "gemma2:2b",
]

# Test cases
TEST_CASES = [
    {
        "name": "Simple Question",
        "prompt": "What is 2+2?",
        "expected_keywords": ["4", "four"],
        "tools": None,
    },
    {
        "name": "Code Generation",
        "prompt": "Write a Python function to calculate fibonacci numbers",
        "expected_keywords": ["def", "fibonacci", "return"],
        "tools": None,
    },
    {
        "name": "Tool Calling - File Read",
        "prompt": "Read the README.md file in the current directory",
        "expected_keywords": ["tool_calls", "read_file"],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file to read"
                            }
                        },
                        "required": ["path"]
                    }
                }
            }
        ],
    },
    {
        "name": "Context Understanding",
        "prompt": "Given this context: 'The user wants to build a web app with React.' What framework should be used for the frontend?",
        "expected_keywords": ["React", "frontend"],
        "tools": None,
    },
    {
        "name": "Reasoning Task",
        "prompt": "If a train leaves station A at 60mph heading toward station B 120 miles away, and another train leaves station B at 40mph heading toward station A, when will they meet?",
        "expected_keywords": ["1.2", "72", "hour"],
        "tools": None,
    },
]


async def test_model(model: str, test_case: Dict[str, Any]) -> Dict[str, Any]:
    """Test a single model with a single test case."""
    print(f"  Testing {model} on '{test_case['name']}'...", end=" ", flush=True)

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": test_case["prompt"]}
                ],
                "temperature": 0.7,
                "max_tokens": 500,
            }

            if test_case["tools"]:
                payload["tools"] = test_case["tools"]

            response = await client.post(
                f"{API_BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                }
            )

            response.raise_for_status()
            data = response.json()

            end_time = time.time()
            duration = end_time - start_time

            # Extract response
            message = data["choices"][0]["message"]
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            # Check if response meets expectations
            score = 0
            max_score = len(test_case["expected_keywords"])

            response_text = content.lower()
            if tool_calls:
                response_text += " " + json.dumps(tool_calls).lower()

            for keyword in test_case["expected_keywords"]:
                if keyword.lower() in response_text:
                    score += 1

            accuracy = (score / max_score * 100) if max_score > 0 else 100

            print(f"✓ {duration:.2f}s (accuracy: {accuracy:.0f}%)")

            return {
                "success": True,
                "duration": duration,
                "accuracy": accuracy,
                "response_length": len(content),
                "used_tools": len(tool_calls) > 0,
            }

    except httpx.TimeoutException:
        print("✗ TIMEOUT")
        return {
            "success": False,
            "error": "timeout",
            "duration": 300.0,
            "accuracy": 0,
        }
    except Exception as e:
        print(f"✗ ERROR: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "duration": 0,
            "accuracy": 0,
        }


async def benchmark_all_models():
    """Run benchmarks on all models."""
    print("=" * 80)
    print("CLIO Model Benchmark Suite")
    print("=" * 80)
    print(f"Testing {len(MODELS)} models with {len(TEST_CASES)} test cases each\n")

    results = {}

    for model in MODELS:
        print(f"\n📊 Benchmarking: {model}")
        print("-" * 80)

        model_results = {
            "total_duration": 0,
            "avg_duration": 0,
            "avg_accuracy": 0,
            "success_rate": 0,
            "test_results": [],
        }

        for test_case in TEST_CASES:
            result = await test_model(model, test_case)
            model_results["test_results"].append({
                "test_name": test_case["name"],
                **result
            })

            if result["success"]:
                model_results["total_duration"] += result["duration"]

        # Calculate averages
        successful_tests = [r for r in model_results["test_results"] if r["success"]]
        total_tests = len(model_results["test_results"])

        if successful_tests:
            model_results["avg_duration"] = model_results["total_duration"] / len(successful_tests)
            model_results["avg_accuracy"] = sum(r["accuracy"] for r in successful_tests) / len(successful_tests)

        model_results["success_rate"] = (len(successful_tests) / total_tests * 100) if total_tests > 0 else 0

        results[model] = model_results

    # Print summary
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'Model':<20} {'Avg Time':<12} {'Accuracy':<12} {'Success Rate':<12} {'Score':<10}")
    print("-" * 80)

    ranked_models = []

    for model, data in results.items():
        avg_time = data["avg_duration"]
        avg_accuracy = data["avg_accuracy"]
        success_rate = data["success_rate"]

        # Calculate overall score (weighted)
        # Speed: 30%, Accuracy: 50%, Success Rate: 20%
        speed_score = max(0, 100 - (avg_time * 10))  # Penalize slower models
        overall_score = (speed_score * 0.3) + (avg_accuracy * 0.5) + (success_rate * 0.2)

        ranked_models.append({
            "model": model,
            "avg_time": avg_time,
            "avg_accuracy": avg_accuracy,
            "success_rate": success_rate,
            "overall_score": overall_score,
        })

        print(f"{model:<20} {avg_time:>6.2f}s     {avg_accuracy:>6.1f}%      {success_rate:>6.1f}%       {overall_score:>6.1f}")

    # Rank models
    ranked_models.sort(key=lambda x: x["overall_score"], reverse=True)

    print("\n" + "=" * 80)
    print("RECOMMENDED MODEL RANKINGS")
    print("=" * 80)

    for i, model_data in enumerate(ranked_models, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        print(f"{medal} {model_data['model']:<20} (Score: {model_data['overall_score']:.1f})")
        print(f"   Speed: {model_data['avg_time']:.2f}s | Accuracy: {model_data['avg_accuracy']:.1f}% | Success: {model_data['success_rate']:.1f}%")

    print("\n" + "=" * 80)
    print("RECOMMENDATION:")
    best_model = ranked_models[0]
    print(f"Use '{best_model['model']}' for the best balance of speed and accuracy!")
    print("=" * 80)

    # Save detailed results
    output_file = Path(__file__).parent / "benchmark_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(benchmark_all_models())
