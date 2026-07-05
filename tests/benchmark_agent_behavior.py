"""Agent-behavior benchmark: score local models on the failure modes observed live.

Runs a fixed task set through the real Agent loop (real tools, read-only /
scratch-scoped permissions) against each model, and counts:
- task success (per-task answer checkers)
- narration stalls (continuation nudges injected)
- false-inability claims (inability nudges injected)
- text-embedded tool calls (recovery events)
- tool calls made, turns used, wall time

Usage:  .venv/bin/python tests/benchmark_agent_behavior.py [model ...]
Defaults to the three local candidates. Results are printed as a table and
saved as JSON next to this file (benchmark_agent_behavior_results.json).
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clio.agent.constants import DEFAULT_SYSTEM_PROMPT  # noqa: E402
from clio.agent.core import Agent  # noqa: E402
from clio.agent.tools import Tools  # noqa: E402
from clio.providers import create_provider  # noqa: E402

BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODELS = [
    "qwen3-coder-unsloth:30b",
    "devstral-small-2:24b",
    "qwen3:30b-a3b",
]
REPO = "/home/gare/projects/cli-o"
TASK_TIMEOUT = 300

# Sentinels injected by the agent's guards; counted from message history.
STALL_NUDGE = "You described a next step but did not call a tool"
INABILITY_NUDGE = "you DO have tool access"

READONLY_PREFIXES = (
    "git ls-remote", "git branch", "git log", "git status", "git diff",
    "git show", "git remote", "git rev-parse", "ls", "cat", "head", "tail",
    "grep", "rg", "find", "wc", "pwd",
)


def head_sha() -> str:
    return subprocess.run(
        ["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()


def make_tasks(scratch: Path):
    sha = head_sha()
    target = scratch / "hello_bench.txt"
    return [
        {
            "name": "git-remote-state",
            "prompt": "whats the latest commit changes pushed to the remote repo for clio?",
            "check": lambda r: sha in r,
            "why": f"must name pushed HEAD {sha}, not misread origin/main",
        },
        {
            "name": "code-lookup",
            "prompt": "which file and variable hold the agent's default system prompt? give file path and variable name",
            "check": lambda r: "constants.py" in r and "DEFAULT_SYSTEM_PROMPT" in r,
            "why": "requires actually searching the code",
        },
        {
            "name": "capability-selfknowledge",
            "prompt": "can you run git commit and push for me if I ask? answer yes or no and explain what happens",
            "check": lambda r: "yes" in r.lower()[:200],
            "why": "no false inability claim",
        },
        {
            "name": "tool-inventory",
            "prompt": "list the names of all tools the clio agent exposes to the model (check the code, don't guess)",
            "check": lambda r: "update_plan" in r and "web_fetch" in r,
            "why": "grounded enumeration incl. newest tool",
        },
        {
            "name": "file-creation",
            "prompt": f"create a file at {target} containing exactly the single line: benchmark ok",
            "check": lambda r: target.exists() and "benchmark ok" in target.read_text(),
            "why": "real state-changing task execution",
        },
    ]


class QuietLogger:
    logger = logging.getLogger("bench")

    def __getattr__(self, name):
        if name.startswith("log_"):
            return lambda *a, **k: None
        raise AttributeError(name)


class NullDB:
    def retrieve_rag_context(self, *a, **k):
        return []

    def add_usage_stat(self, *a, **k):
        pass

    def save_plan(self, *a, **k):
        pass


def make_agent(model: str, scratch: Path) -> Agent:
    a = object.__new__(Agent)
    a.provider = create_provider("openai-compatible", {"base_url": BASE_URL, "api_key": "ollama"})
    a.current_model = model
    a.current_provider_name = "bench"
    a.session_logger = QuietLogger()
    a.history_db = NullDB()
    a.conversation_id = 1
    a.system_prompt = DEFAULT_SYSTEM_PROMPT
    a.original_working_dir = None
    a.recent_files = []

    async def approve(op, details, diff_info=None):
        cmd = details.replace("Run command: ", "").strip()
        if cmd.startswith(READONLY_PREFIXES):
            return True
        # writes/edits only inside the scratch dir
        return str(scratch) in details

    a.tools = Tools(permission_callback=approve)
    a.token_callback = None
    a.tool_callback = None
    a.messages = []
    a.last_prompt_tokens = 0
    a._context_window_cache = {}

    async def noop(*args, **kwargs):
        pass

    a._save_message_with_rag = noop
    return a


def count_events(messages):
    stalls = sum(
        1 for m in messages
        if m.get("role") == "user" and STALL_NUDGE in (m.get("content") or "")
    )
    inability = sum(
        1 for m in messages
        if m.get("role") == "user" and INABILITY_NUDGE in (m.get("content") or "")
    )
    recovered = sum(
        1 for m in messages if any(
            str(tc.get("id", "")).startswith("recovered_")
            for tc in (m.get("tool_calls") or [])
        )
    )
    tool_calls = sum(len(m.get("tool_calls") or []) for m in messages)
    return stalls, inability, recovered, tool_calls


async def run_model(model: str, scratch: Path):
    results = []
    for task in make_tasks(scratch):
        agent = make_agent(model, scratch)  # fresh history per task
        t0 = time.perf_counter()
        try:
            answer = await asyncio.wait_for(agent.chat(task["prompt"]), timeout=TASK_TIMEOUT)
            error = None
        except asyncio.TimeoutError:
            answer, error = "", "timeout"
        except Exception as e:
            answer, error = "", f"{type(e).__name__}: {e}"
        elapsed = time.perf_counter() - t0
        stalls, inability, recovered, tool_calls = count_events(agent.messages)
        ok = False
        try:
            ok = bool(task["check"](answer)) and error is None
        except Exception:
            pass
        results.append({
            "task": task["name"], "success": ok, "seconds": round(elapsed, 1),
            "stall_nudges": stalls, "inability_nudges": inability,
            "recovered_tool_calls": recovered, "tool_calls": tool_calls,
            "error": error,
            "answer_head": (answer or "")[:160],
        })
        print(f"  {task['name']:<26} {'PASS' if ok else 'FAIL':<5} "
              f"{elapsed:6.1f}s  stalls={stalls} inability={inability} "
              f"recovered={recovered} tools={tool_calls}"
              + (f"  [{error}]" if error else ""), flush=True)
    return results


async def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    os.chdir(REPO)
    all_results = {}
    with tempfile.TemporaryDirectory(prefix="clio-bench-") as td:
        scratch = Path(td)
        for model in models:
            print(f"\n=== {model} ===", flush=True)
            all_results[model] = await run_model(model, scratch)
            # clean scratch between models so file-creation is fair
            for f in scratch.iterdir():
                f.unlink()

    print("\n=== SUMMARY ===")
    print(f"{'model':<28} {'pass':<6} {'stalls':<7} {'inability':<10} {'recovered':<10} {'avg s':<6}")
    for model, res in all_results.items():
        passes = sum(r["success"] for r in res)
        stalls = sum(r["stall_nudges"] for r in res)
        inab = sum(r["inability_nudges"] for r in res)
        rec = sum(r["recovered_tool_calls"] for r in res)
        avg = sum(r["seconds"] for r in res) / len(res)
        print(f"{model:<28} {passes}/{len(res):<4} {stalls:<7} {inab:<10} {rec:<10} {avg:<6.1f}")

    out = Path(__file__).parent / "benchmark_agent_behavior_results.json"
    out.write_text(json.dumps(all_results, indent=2))
    print(f"\nresults saved: {out}")


if __name__ == "__main__":
    asyncio.run(main())
