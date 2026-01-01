# Performance Audit - Batch Plan

*Organized by dependency and impact*

## Audit Order Strategy

1. **Hot path files** (most frequently executed, biggest impact)
2. **Large files** (more code = more opportunities for issues)
3. **Dependencies first** (lower layers before higher layers)

---

## 📍 GROUP 1: UI Layer (1735 lines)
**Why first:** We've been actively changing this. Fresh in memory. Highest LOC.

```
src/clio/ui/app.py                    (1735 lines) - Main TUI app, event handlers, state management
src/clio/ui/thinking_indicator.py    (~50 lines)  - Token counter widget
src/clio/ui/textarea_autocomplete.py (~150 lines) - Custom text input
```

**Focus areas:**
- Widget caching (query_one() calls)
- Event handler efficiency
- Message storage duplication (3 lists)
- Tool panel streaming complexity
- Resize handler performance
- Status bar update frequency

---

## 📍 GROUP 2: Agent Core + Tools (1253 lines)
**Why second:** Heart of the app. Depends on providers/history. Called on every message.

```
src/clio/agent/core.py        (513 lines)  - Main chat loop, message handling, tool orchestration
src/clio/agent/tools.py       (740 lines)  - Tool definitions (read_file, edit_file, bash, etc)
src/clio/agent/session_logger.py (~100) - Per-session logging
```

**Focus areas:**
- Message building (system prompt + RAG + history)
- Tool execution patterns
- Async/await usage
- DateTime import on every chat()
- Tool result formatting

---

## 📍 GROUP 3: Data Persistence (800 lines)
**Why third:** Called frequently. Database operations are often bottlenecks.

```
src/clio/history/database.py  (570 lines) - SQLite operations, RAG integration
src/clio/rag/retriever.py     (230 lines) - ChromaDB vector search
src/clio/rag/embeddings.py    (~150 lines) - Sentence transformers model
```

**Focus areas:**
- Connection pooling vs shared connection
- Async message insertion
- RAG model loading (already optimized but verify)
- Query efficiency
- Excessive get_session_usage() calls

---

## 📍 GROUP 4: Provider Layer (376 lines)
**Why fourth:** Abstraction layer. Less frequently changed. Smaller surface area.

```
src/clio/providers/base.py              (109 lines) - Abstract base class
src/clio/providers/openai_compatible.py (267 lines) - OpenAI/Ollama/OpenWebUI
src/clio/providers/anthropic.py         (~150 lines) - Claude API
src/clio/providers/capabilities.py      (~50 lines)  - Tool support detection
src/clio/providers/schemas.py           (~50 lines)  - Shared types
```

**Focus areas:**
- Streaming implementation
- Error handling patterns
- Tool call parsing
- Response format conversion

---

## 📍 GROUP 5: Config & Context (400 lines)
**Why fifth:** Mostly initialization code. Called once or infrequently.

```
src/clio/config/manager.py    (~200 lines) - Config loading/saving
src/clio/config/schema.py     (~150 lines) - Pydantic schemas
src/clio/context/manager.py   (~200 lines) - File context (@ mentions)
src/clio/commands/router.py   (~100 lines) - Slash command routing
```

**Focus areas:**
- Config reload frequency
- File watching overhead
- Context manager token counting

---

## 📍 GROUP 6: Entry Points (200 lines)
**Why sixth:** Thin orchestration layer. Usually fine.

```
src/clio/cli.py       (~150 lines) - Argument parsing, app launch
src/clio/__main__.py  (~20 lines)  - Entry point
```

**Focus areas:**
- Startup time
- Import overhead
- Unnecessary initialization

---

## 📍 GROUP 7: Auxiliary (500 lines - OPTIONAL)
**Why last:** Nice-to-have features. Not critical path.

```
src/clio/billing/openai_billing.py  (~150 lines) - OpenAI admin API
src/clio/ide_bridge.py              (~100 lines) - IDE integration (optional)
src/clio/ide_integration.py         (~100 lines) - Legacy?
src/clio/vscode_mode.py             (~100 lines) - VSCode mode
src/clio/vscode_protocol.py         (~50 lines)  - VSCode protocol
```

**Decision:** Audit only if time permits. Not hot path.

---

## 🎯 Current Status

- [x] GROUP 1: UI Layer - **COMPLETE** (Phase 1: Quick wins done - removed ~97 lines, cached colors)
- [x] GROUP 2: Agent Core + Tools - **AUDIT COMPLETE** (found debug logs + datetime import issues)
- [ ] GROUP 3: Data Persistence
- [ ] GROUP 4: Provider Layer
- [ ] GROUP 5: Config & Context
- [ ] GROUP 6: Entry Points
- [ ] GROUP 7: Auxiliary (optional)

---

## Audit Process Per Group

1. **Read files together** (understand dependencies)
2. **Flag issues** (refer to performance-audit-checklist.md)
3. **Propose changes** (concise, Pythonic)
4. **Verify with user** (don't make assumptions)
5. **Implement + test**
6. **Move to next group**

---

## Notes

- Total LOC to audit: ~4500 lines (excluding auxiliary)
- Largest files: app.py (1735), tools.py (740), database.py (570)
- We're not rewriting - we're simplifying and optimizing
- Measure before/after for each group
