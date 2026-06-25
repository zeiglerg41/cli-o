# clio Architecture Audit — clio vs. Claude Code

**Date:** 2026-06-24
**Purpose:** Map clio's current architecture against Claude Code's (per public reverse-engineering write-ups), identify gaps, and prioritize work. Goal is **a private, local, self-owned coding agent that is as capable as we can make it** — resilience against losing hosted Claude Code access, not a commercial competitor.

> Sourcing note: the clio sections are grounded in the actual source tree (file:line references verified 2026-06-24). The Claude Code sections come from public reverse-engineering write-ups and the 2026 source-map leak coverage; structural claims are credible, but specific performance numbers from those write-ups are **unverified** and flagged as such.

---

## 1. Executive Summary

clio is a **more complete and conventional agent than expected**. It is a multi-provider, streaming, tool-calling REPL agent with persistent history, RAG, a solid permission model, and IDE diff integration. Its core agent loop is standard and sound.

The gap to Claude Code is **not** in the basics (tools, loop, permissions — clio has credible versions of all three). It is concentrated in **long-horizon capability and extensibility**:

- **No context compaction/summarization** — the single biggest capability ceiling. Long sessions silently drop older turns (sliding window), recovered only partially via RAG.
- **No persistent project memory** (no `CLAUDE.md` equivalent).
- **No sub-agent delegation, no parallel tool execution, no task/todo tracking** — the "scaffolding" that makes weaker models behave like stronger ones.
- **No MCP / plugin / hook extensibility** — everything is hardcoded in Python.

For a **local-model** setup these scaffolding gaps matter *more* than they do for Claude, because the model is weaker and leans harder on structure. (Claude Code's own reverse-engineered breakdown is ~1.6% agent logic / ~98% operational scaffolding — that ratio is the whole point.)

---

## 2. clio Current Architecture

### 2.1 Layer stack

```
CLI entry (Click)            clio.cli:main  [pyproject.toml:46]
  └─ REPL (prompt_toolkit)   ClioREPL.run  [cli_repl.py:488]  — sequential loop, live streaming, metrics, spinner
       └─ CommandRouter      commands/router.py  — /slash commands, @mentions
            └─ Agent loop     agent/core.py:604-847  — agentic loop, max 20 turns
                 ├─ Tools     agent/tools.py  — 9 tools + permission callbacks
                 ├─ Providers providers/*  — factory: openai-compatible/openai/anthropic/gemini/deepseek/grok
                 ├─ Context    context/manager.py  — @file/@folder, tiktoken budget
                 ├─ History    history/database.py  — SQLite: conversations/messages/usage_stats
                 ├─ RAG        rag/*  — ChromaDB + all-MiniLM-L6-v2, hybrid scoring
                 └─ IDE bridge ide_bridge.py (WebSocket) + vscode_protocol.py (stdio)
```

### 2.2 Agent loop (`agent/core.py`)

- Standard agentic loop, **`max_turns = 20`** (core.py:594); exits when the model returns no tool calls (core.py:730).
- **Infinite-loop guard:** identical tool call 3× in a row → abort with the last error (core.py:754-792).
- **Rate-limit handling:** 429 detection, up to 5 retries, exponential backoff + jitter, honors server-provided wait time (core.py:631-671).
- **Usage/cost tracking** per turn into `usage_stats` (core.py:694-714).
- **Streaming vs non-streaming:** if a `token_callback` is set and the provider exposes `chat_streaming`, it streams (core.py:609-621).

### 2.3 Tools (`agent/tools.py`) — 9 total

| Tool | Purpose |
|---|---|
| `read_file`, `write_file`, `edit_file` | File I/O; write/edit produce diff previews and gate on permission |
| `execute_bash` | Shell, with safety classification (see 2.4) |
| `list_directory` | Directory listing |
| `grep_files` | ripgrep/grep content search |
| `find_files` | name-pattern file search (caps at 100) |
| `web_search` | DuckDuckGo HTML search |
| `web_fetch` | URL → text/JSON, grounded, 100KB cap |

Tools are exposed as OpenAI function-calling JSON (`get_tool_definitions`, tools.py:548-751), gated per model by a capability matrix (`providers/capabilities.py`), and dispatched via an if/elif map (tools.py:753-774).

### 2.4 Permission model (`agent/command_safety.py`, `cli_repl.py`)

Two layers:
1. **Bash classification:** `is_blocked()` (catastrophic patterns: `rm -rf /`, `mkfs.`, `dd if=`, fork bomb, `curl|bash`, …) and `is_readonly_command()` (auto-run allowlist: `ls/cat/grep/find/git status|log|diff|…`). Anything with redirects, substitution, chaining, `sudo`, or unknown commands → gated.
2. **Callback gating** for `write_file`/`edit_file`/non-readonly bash → `y/n/a` prompt with diff preview; `a` auto-approves for the session.
3. **User-extensible** via `~/.clio/config.json > permissions` (`extra_readonly_commands`, `extra_readonly_git_subcommands`, `extra_blocked_patterns`).

### 2.5 Context, RAG, persistence

- **Context per turn:** system prompt + dynamic (date, cwd, recently-edited files) + optional RAG block + sliding window of recent messages. `@file` mentions are nudged toward `read_file` tool calls rather than injected.
- **Window management:** keep last 20 messages / 15k tokens (tiktoken `cl100k_base`); hard fallback to last 10 if over budget (core.py:513-548). **No summarization.**
- **RAG:** ChromaDB at `~/.clio/chroma`, `all-MiniLM-L6-v2` embeddings, hybrid score `0.6*semantic + 0.4*recency`, triggered only when history > 20 messages (core.py:462-471). Embedding/writes run off the event loop.
- **Persistence:** SQLite at `~/.clio/history.db` (`conversations`, `messages`, `usage_stats`); resumable via `--continue`; auto-titles; cleanup keeps N recent + starred.
- **Observation masking:** tool-result messages are dropped on resume to save tokens (core.py:222-233).
- **Session logs:** text logs at `~/.clio/logs/session_*.log`.

### 2.6 Providers & local-model resilience

- Factory supports **6 provider types**: `openai-compatible`, `openai`, `anthropic`, `gemini`, `deepseek`, `grok` (providers/__init__.py).
- Ollama/OpenWebUI auto-detected (base_url / `:11434`).
- **Local-model tool-call recovery:** when a local model emits tool calls as text, clio parses **XML (Qwen3-Coder style)** and **JSON** fallbacks back into structured calls (openai_compatible.py:21-130). This is key robustness for non-Claude backends.

### 2.7 What clio does *better* than (or differently from) Claude Code

- **Multi-provider failover** baked in (Claude Code is Anthropic-only). Directly serves the resilience goal.
- **Persistent SQLite history + RAG + cost tracking** as first-class storage.
- **Local-first**: designed around Ollama/local GPU, with tool-call recovery for weak models.

---

## 3. Claude Code Architecture (from public write-ups)

> Credible structure; **perf numbers unverified**.

- **Main loop:** documented as the `nO` loop fed by an `h2A` async message queue (real minified identifiers from the leak). Conceptually similar to clio's loop but with a streaming message-bus design.
- **Tools (~11):** `View`/`Edit`/`Write`/`Replace`, `LS`, `GlobTool`, `GrepTool`, `Bash`, `BatchTool` (parallel/serial multi-tool), `WebFetchTool`, `ReadNotebook`/`NotebookEditCell`, and **`dispatch_agent`** (sub-agents with a restricted toolset).
- **Permissions:** command **prefix extraction** (e.g. `git commit`) with approval for unfamiliar prefixes; uses a **cheap secondary model (Haiku)** to classify commands / detect injection. Permission *modes* (e.g. auto-accept edits, plan mode).
- **Context compaction (`wU2`/`AU2`):** when context approaches the model limit, score messages by importance, retain the top fraction, **LLM-summarize the rest**, and persist memory — enabling very long sessions. **clio has no equivalent.**
- **Memory:** `CLAUDE.md` project/user memory loaded into context.
- **Sub-agents:** tiered agents with restricted tools for search/parallel work, keeping the main context clean.
- **TodoWrite:** an explicit task list the model maintains across a multi-step task.
- **Dual-model:** big model for reasoning, small model for cheap parsing (bash prefixes, titling).
- **MCP + hooks:** external tool servers (MCP) and lifecycle hooks for extensibility.
- **UI:** React/Ink terminal renderer.

---

## 4. Side-by-Side

| Capability | clio | Claude Code |
|---|---|---|
| Agentic tool loop | ✅ 20-turn, loop-guard | ✅ |
| File tools (read/write/edit + diff) | ✅ + IDE diff bridge | ✅ |
| Search tools (grep/find) | ✅ `grep_files`/`find_files` | ✅ Grep/Glob |
| Web tools | ✅ search + fetch | ✅ WebFetch |
| Bash w/ safety gating | ✅ allowlist + blocklist + callback | ✅ prefix gating (+Haiku classifier) |
| Permission modes (plan/auto-edit) | ⚠️ session auto-approve only | ✅ multiple modes |
| Multi-provider / failover | ✅ 6 types | ❌ Anthropic only |
| Local-model tool-call recovery | ✅ XML/JSON fallback | n/a |
| Persistent history + resume | ✅ SQLite | ⚠️ (session-based) |
| RAG over history | ✅ ChromaDB hybrid | ❌ (uses compaction instead) |
| **Context compaction/summarization** | ❌ | ✅ `wU2` |
| **Project memory (`CLAUDE.md`)** | ❌ | ✅ |
| **Sub-agents / delegation** | ❌ | ✅ `dispatch_agent` |
| **Parallel tool execution** | ❌ sequential | ✅ `BatchTool` |
| **Task/todo tracking** | ❌ | ✅ `TodoWrite` |
| Dual-model (cheap classifier) | ❌ | ✅ |
| MCP external tools | ❌ | ✅ |
| Hooks / plugins | ❌ | ✅ |
| Reasoning/thinking display | ❌ (stripped) | ✅ |
| Cost tracking | ✅ DB (not surfaced in UI) | ✅ |
| Tests (agent/REPL) | ❌ none visible | n/a |

---

## 5. Gap Analysis (prioritized for "capable local agent")

### Tier 1 — biggest capability unlocks
1. **Context compaction / summarization.** Removes the long-session ceiling. When approaching the token budget, summarize older turns (with the local model) into a running summary instead of dropping them. Highest leverage for real multi-step work.
2. **Project memory (`CLIO.md`/`CLAUDE.md`).** Load a per-project instructions/notes file into the system prompt. Cheap to build, large quality gain, persists conventions across sessions.
3. **Task/todo tracking (`TodoWrite`-style).** A visible, model-maintained checklist. Disproportionately helps *weaker local models* stay on track over multi-step tasks.

### Tier 2 — strong multipliers
4. **Sub-agent delegation.** A `dispatch_agent`-style tool that spawns a restricted child agent for search/exploration and returns only the conclusion — keeps the main context lean (synergizes with #1).
5. **Parallel tool execution.** Run independent read-only tool calls concurrently (clio already collects tool calls in a batch; execution is sequential today).
6. **Model performance / fit.** The current default (qwen2.5:32B q4) only partially fits the 3090 (44/65 layers → ~2.2 tok/s). A model that fully fits 24 GB (e.g. a 14B, or lighter ~30B quant) is a large day-to-day usability win. *Ops/config, not code.*

### Tier 3 — extensibility & polish
7. **MCP client support** — unlock external tool servers without hardcoding.
8. **Hooks / plugin system** — user commands and lifecycle hooks without forking.
9. **Permission modes** — plan mode, pre-approved workflow allowlists.
10. **Reasoning display** — surface `<think>` for reasoning models instead of stripping.
11. **Tests** — integration tests around the agent loop + tools before further refactors.

---

## 6. Recommended Sequence

1. **Project memory (`CLIO.md`)** — smallest, immediate quality lift, low risk.
2. **Context compaction** — the core capability gap; do early since later features depend on long-session stability.
3. **TodoWrite-style task tracking** — pairs with compaction to sustain multi-step tasks on local models.
4. **Sub-agent delegation** + **parallel tool calls** — scale to bigger tasks while keeping context lean.
5. Extensibility (MCP, hooks), permission modes, reasoning display, tests.

Throughout: treat the **system prompt + scaffolding** as the main lever for local-model quality (Claude Code's ~98%-infrastructure ratio is the guiding intuition).

---

## 7. Sources

- clio source tree at `/home/gare/projects/cli-o/src/clio/` (file:line refs verified 2026-06-24).
- Kir Shatrov, "Reverse engineering Claude Code" — https://kirshatrov.com/posts/claude-code-internals
- BrightCoding, "Inside Claude Code: A Deep-Dive Reverse Engineering Report" — https://www.blog.brightcoding.dev/2025/07/17/inside-claude-code-a-deep-dive-reverse-engineering-report/
- 2026 source-map leak coverage (Cybernews, The IPKat, TechCrunch) for context on availability/provenance.

*Performance figures from the reverse-engineering write-ups (throughput, compression ratios, gate latency) are unverified and excluded from conclusions.*
