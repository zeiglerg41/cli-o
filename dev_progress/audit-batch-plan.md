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

## 📍 GROUP 3: Data Persistence (800 lines) ✅ COMPLETE
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

**Changes implemented:**
1. ✅ Fixed bare except in embeddings.py (better error logging)
2. ✅ Removed debug logging in hot path (retriever.py - 2 lines)
3. ✅ Extracted title generation helper method (database.py - removed ~16 lines duplication)
4. ✅ Added collection caching per conversation_id (retriever.py - performance improvement)
5. ✅ Consolidated add_message methods (retriever.py - removed ~14 lines duplication)

**Total impact:** ~30 lines removed, improved caching, better maintainability

---

## 📍 GROUP 4: Provider Layer (1419 lines) ✅ BATCH 1 COMPLETE
**Why fourth:** Abstraction layer. Less frequently changed. Smaller surface area.

```
src/clio/providers/base.py              (109 lines) - Abstract base class
src/clio/providers/openai_compatible.py (267 lines) - OpenAI/Ollama/OpenWebUI
src/clio/providers/anthropic.py         (~200 lines) - Claude API
src/clio/providers/gemini.py            (~300 lines) - Google Gemini API
src/clio/providers/capabilities.py      (~50 lines)  - Tool support detection
src/clio/providers/schemas.py           (~50 lines)  - Shared types
```

**Focus areas:**
- Streaming implementation
- Error handling patterns
- Tool call parsing
- Response format conversion

**Changes implemented (Batch 1):**
1. ✅ Removed production debug logging in openai_compatible.py (13 lines - **SECURITY FIX**)
2. ✅ Removed duplicate json imports in openai_compatible.py and anthropic.py
3. ✅ Extracted `_build_headers()` helper method in openai_compatible.py (~8 lines deduplication)

**Total impact:** ~21 lines removed, fixed security issue (debug logs writing to /tmp), better code organization

**Note:** gemini.py and other providers not yet audited - can continue if needed

---

## 📍 GROUP 5: Config & Context (400 lines) ✅ BATCH 1 COMPLETE
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

**Changes implemented (Batch 1):**
1. ✅ Removed unused asyncio import in context/manager.py (1 line cleanup)
2. ✅ Extracted `_resolve_path()` helper method in context/manager.py (~15 lines deduplication)
3. ✅ Added DRY principle to command registration - single source of truth in CommandRouter
   - Commands now registered with descriptions in app.py
   - Autocomplete pulls from router dynamically via `get_all_commands()`
   - Removed hardcoded command list from autocomplete (~12 lines removed)

**Total impact:** ~28 lines removed, better maintainability, added `/prompt` command for editing system prompt

---

## 📍 GROUP 6: Entry Points (200 lines) ✅ COMPLETE
**Why sixth:** Thin orchestration layer. Usually fine.

```
src/clio/cli.py       (~250 lines) - Argument parsing, app launch
src/clio/__main__.py  (~6 lines)   - Entry point
```

**Focus areas:**
- Startup time
- Import overhead
- Unnecessary initialization

**Changes implemented:**
1. ✅ Removed duplicate datetime import in cli.py (already imported at top)
2. ✅ Added `MAX_RECENT_CONVERSATIONS = 20` constant to eliminate magic numbers
3. ✅ Replaced all hardcoded `20` and `limit=20` with constant (4 occurrences)
4. ✅ Simplified asyncio import in vscode command (`from asyncio import run`)

**Total impact:** Removed 1 duplicate import, eliminated 4 magic numbers, cleaner code

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
- [x] GROUP 2: Agent Core + Tools - **COMPLETE** (found debug logs + datetime import issues)
- [x] GROUP 3: Data Persistence - **COMPLETE** (removed ~30 lines, added caching, consolidated duplicate code)
- [x] GROUP 4: Provider Layer - **BATCH 1 COMPLETE** (removed ~21 lines, fixed security issue, deduplication)
- [x] GROUP 5: Config & Context - **BATCH 1 COMPLETE** (removed ~28 lines, DRY principles, added /prompt command)
- [x] GROUP 6: Entry Points - **COMPLETE** (removed duplicate import, eliminated magic numbers)
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

---

## 🎁 Bonus Features Implemented

### Config Change Detection
**File:** `src/clio/ui/app.py` - `_cmd_config()`

**Feature:** `/config` command now detects if user made changes:
- Shows "No changes made to config" (dim) if no edits
- Shows "✓ Config file edited... Restart clio" (dim) if changes made

**Technical challenge solved:** `self.suspend()` breaks Textual UI rendering
- **Solution:** Use `self.set_timer(0.01, callback)` to delay message display until after UI settles
- This allows external editor to run while maintaining proper message display afterward

**Impact:** Better UX, users get immediate feedback on whether config was modified
