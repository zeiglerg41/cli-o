"""Sub-agent dispatch: run a research task in an isolated context.

The parent agent hands a natural-language task to a fresh Agent instance that
has its OWN message history and a restricted read-only toolset. The sub-agent
explores (read/grep/find/list across as many turns as it needs, within caps)
and only its final answer returns to the parent as a tool result — none of
its intermediate reading ever touches the parent's context window.

On a single local GPU the win is context isolation, not wall-clock
parallelism (concurrent generations share the same compute), so dispatch is
sequential by design.

Guardrails, each from an observed failure mode:
- read-only tools only (no write/edit/bash/web, no side effects)
- no recursive dispatch (a sub-agent cannot spawn sub-agents)
- hard turn cap and wall-clock timeout (a hosted model once ground a task
  for a full 5 minutes; the caps make that bounded)
- sub-agent token usage is forwarded to the parent's ledger so /usage and
  the context meter stay honest
"""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Agent

SUBAGENT_ALLOWED_TOOLS = {"read_file", "grep_files", "find_files", "list_directory"}
SUBAGENT_MAX_TURNS = 8
SUBAGENT_TIMEOUT_SECONDS = 240

SUBAGENT_SYSTEM_PROMPT = """You are a focused research sub-agent inside a coding assistant. You are given ONE task. Investigate it using your read-only tools and return your findings.

RULES:
- Use tools immediately; do not narrate plans. Investigate until you can answer.
- Your final message is returned VERBATIM to the main agent as data. Make it a dense, factual report: findings first, then evidence.
- Cite locations as file_path:line_number for everything you report.
- If you cannot find something, say exactly what you searched (patterns, paths) so the main agent doesn't repeat the work.
- No greetings, no offers of further help, no questions back. You get one shot.

Available tools: read_file, grep_files, find_files, list_directory"""


DISPATCH_AGENT_DEFINITION = {
    "type": "function",
    "function": {
        "name": "dispatch_agent",
        "description": (
            "Delegate a self-contained research/search task to a sub-agent with "
            "its own context window and read-only file tools. The sub-agent "
            "explores (multiple greps/reads) and returns only its findings, "
            "keeping large intermediate file contents out of your context. "
            "Use for questions that need reading several files (e.g. 'find where "
            "permissions are enforced and how'). Do NOT use for single lookups "
            "you can do with one tool call, or for anything requiring edits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The complete, self-contained task. Include everything the "
                        "sub-agent needs — it cannot see this conversation."
                    ),
                }
            },
            "required": ["task"],
        },
    },
}


class _ForwardingDB:
    """Forwards the sub-agent's usage rows to the parent ledger; drops the rest.

    The sub-agent must not create conversations, save messages, or touch RAG —
    its transcript is disposable. Its token spend is real, though, so usage
    stats flow through to the parent's conversation.
    """

    def __init__(self, parent_db, parent_conversation_id):
        self._db = parent_db
        self._cid = parent_conversation_id

    def add_usage_stat(self, conversation_id=None, **kwargs):
        try:
            self._db.add_usage_stat(conversation_id=self._cid, **kwargs)
        except Exception:
            pass

    def retrieve_rag_context(self, *args, **kwargs):
        return []

    def save_plan(self, *args, **kwargs):
        pass


def _make_subagent(parent: "Agent") -> "Agent":
    """Build a lightweight sibling Agent sharing the parent's provider/model
    but with isolated history, restricted tools, and no persistence."""
    from .core import Agent
    from .tools import Tools

    sub = object.__new__(Agent)
    sub.provider = parent.provider
    sub.current_model = parent.current_model
    sub.current_provider_name = parent.current_provider_name
    sub.config_manager = parent.config_manager
    sub.session_logger = parent.session_logger
    sub.history_db = _ForwardingDB(parent.history_db, parent.conversation_id)
    sub.conversation_id = parent.conversation_id
    sub.system_prompt = SUBAGENT_SYSTEM_PROMPT
    sub.original_working_dir = parent.original_working_dir
    sub.recent_files = []
    sub.tools = Tools(
        permission_callback=parent.tools.permission_callback,
        allowed_tools=set(SUBAGENT_ALLOWED_TOOLS),
    )
    sub.token_callback = None  # sub-agent output is data, never streamed to UI
    sub.messages = []
    sub.last_prompt_tokens = 0
    sub._context_window_cache = parent._context_window_cache
    sub._tool_support_cache = parent._tool_support_cache
    sub.allow_subagents = False  # no recursion
    sub.max_turns = SUBAGENT_MAX_TURNS

    # Surface the sub-agent's tool calls in the parent UI, prefixed so the
    # user can tell delegated work from the main agent's own calls.
    if parent.tool_callback is not None:
        parent_cb = parent.tool_callback

        async def prefixed_cb(tool_name, arguments, result):
            await parent_cb(f"agent:{tool_name}", arguments, result)

        sub.tool_callback = prefixed_cb
    else:
        sub.tool_callback = None

    async def _no_persist(*args, **kwargs):
        pass

    sub._save_message_with_rag = _no_persist
    return sub


async def run_subagent(parent: "Agent", task: str) -> str:
    """Run one dispatched task to completion and return its report."""
    if not task or not task.strip():
        return "Error: dispatch_agent requires a non-empty 'task'"
    sub = _make_subagent(parent)
    parent.session_logger.logger.info(f"Sub-agent dispatched: {task[:120]}")
    try:
        result = await asyncio.wait_for(
            sub.chat(task), timeout=SUBAGENT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        parent.session_logger.logger.warning("Sub-agent timed out")
        return (
            f"Sub-agent timed out after {SUBAGENT_TIMEOUT_SECONDS}s. "
            "Partial work is discarded; try a narrower task or investigate directly."
        )
    except Exception as e:
        parent.session_logger.logger.warning(f"Sub-agent failed: {e}")
        return f"Sub-agent failed: {e}"
    parent.session_logger.logger.info(f"Sub-agent completed ({len(result)} chars)")
    return result
