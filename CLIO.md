# CLIO.md — project memory for clio

Standing context and conventions for working on **clio**, a self-hosted, local-first
AI coding assistant (a privately-owned alternative to Claude Code). Follow these.

## What this project is
- Python package under `src/clio/`. Entry point: `clio.cli:main` (`pyproject.toml`).
- A streaming REPL agent: prompt_toolkit + rich UI, an agentic tool loop (max 20 turns),
  10 tools, a permission layer, SQLite history + RAG, and multi-provider support
  (openai-compatible / openai / anthropic / gemini / deepseek / grok).
- Goal: a resilient personal coding agent that keeps working if hosted tools go away.
  See `planning/ARCHITECTURE-AUDIT.md` for the full architecture, gaps, and roadmap.

## How to run / test
- Use the project virtualenv: `.venv/bin/python` (there is no system `python`).
- Syntax check before claiming anything works: `.venv/bin/python -m py_compile <files>`.
- The CLI launches with `clio`. Local models run via Ollama at `http://localhost:11434`.

## Local model backend (Ollama)
- Ollama runs as a **systemd service** (`User=ollama`), model store at
  `/usr/share/ollama/.ollama/models`. Start it with `sudo systemctl start ollama`.
- The `G:` drive line in `/etc/fstab` needs `nofail` (a missing drive otherwise
  cascades through `local-fs.target` → `sysinit.target` and cancels ollama's start).

## Conventions / guardrails
- **Verify before claiming done.** Never say fixed/working/passing without running a
  command or making a direct observation and reading the output. State hypotheses as
  "strongest candidate" until confirmed live.
- Match surrounding code style. Keep changes tight and tested.
- Write paths robustly: file/dir tools resolve via `_resolve_path()` (expands `~`).

## Roadmap (from the architecture audit)
1. ✅ Project memory (this file / `CLIO.md` loading)
2. ✅ Context compaction / summarization (`agent/compaction.py`, auto + `/compact`;
   state-snapshot pattern adapted from Apache-2.0 Gemini CLI / Codex CLI)
3. ✅ Task/todo tracking (`update_plan` tool, Codex CLI schema; plan re-injected
   into the system prompt each turn)
4. Sub-agents + parallel tool execution  ← NEXT
5. Extensibility: MCP client, hooks/plugins

## Shipped hardening (2026-07-04)
- Persistent context meter: prompt_toolkit bottom toolbar showing used/window
  tokens (`agent/context_window.py`; Ollama runtime query > config override map
  `context_windows` > known-families table).
- Anti-hallucination: capability manifest + grounding rules in the system prompt,
  runtime guard that retries on false "I don't have access" claims (`core.py`).
- Tool-call recovery: calls emitted as literal JSON text are parsed and executed
  through the normal permission path (`agent/tool_call_recovery.py`).
- Git workflow recipes in the system prompt (ls-remote for pushed state,
  newest-first log order, destructive-command prohibition).
