# Performance & Maintainability Audit Checklist

*Created: 2025-01-01*
*Status: NEEDS INVESTIGATION*

Quick wins and potential issues to check. Not definitive - investigate first.

## 🔴 High Priority (Performance Impact)

### Database Operations
- [ ] **SQLite connection pooling** - Currently creating new connections. Single shared connection?
- [ ] **Repeated `get_session_usage()` calls** - Called on every status bar update. Cache it?
- [ ] **Message insertion in hot path** - `add_message_async()` called synchronously in some places. All async?
- [ ] **RAG vector store writes** - Check if ChromaDB is being flushed efficiently

### Async/Await Patterns
- [ ] **`asyncio.create_task()` fire-and-forget** - Are we creating too many background tasks?
- [ ] **Blocking I/O in async context** - Search for `open()`, `json.load()` in async functions
- [ ] **System prompt date calculation** - `datetime.now()` called on every chat(). Move to init or cache?

### UI Updates
- [ ] **Tool panel updates** - Calling `tool_panel.update()` on every tool call. Batch with timer?
- [ ] **Status bar refresh rate** - Updated on every message. Debounce?
- [ ] **RichLog writes** - Are we writing too frequently? Batch messages?
- [ ] **Resize handler** - Clearing and re-rendering ALL messages. Optimize?

## 🟡 Medium Priority (Code Quality)

### Code Duplication
- [ ] **Tool formatting logic** - Similar if/elif blocks in multiple places. Extract to function?
- [ ] **Color maps access** - `self._get_colors()` called repeatedly. Cache result?
- [ ] **Error handling patterns** - Try/except blocks duplicated. Decorator pattern?
- [ ] **Panel creation** - `_create_panel()` and `_write_message()` overlap. Consolidate?

### Import Organization
- [ ] **Runtime imports** - `from rich.markdown import Markdown as RichMarkdown` inside functions. Move to top?
- [ ] **Unused imports** - Check for imports that aren't used
- [ ] **Circular import risk** - Verify no circular dependencies

### State Management
- [ ] **Widget lookups** - `self.query_one("#tool-calls-panel")` called multiple times. Cache widget refs?
- [ ] **Global state tracking** - Multiple tracking variables (`current_tool_calls_text`, `pending_permission`, etc). Consolidate?
- [ ] **Message storage duplication** - `self.messages`, `self.conversation_history`, `self.display_messages`. Unify?

## 🟢 Low Priority (Polish)

### String Operations
- [ ] **F-string consistency** - Mix of f-strings, .format(), and concatenation. Standardize to f-strings
- [ ] **Path operations** - Using string concatenation vs Path objects. Use pathlib consistently
- [ ] **JSON serialization** - Multiple `json.dumps()` calls. Check if needed

### Error Handling
- [ ] **Broad exception catches** - `except Exception as e:` too generic. Be specific
- [ ] **Silent failures** - Some errors logged but not surfaced. User feedback?
- [ ] **Traceback logging** - Are we logging too much or too little?

### Debug Code
- [ ] **Debug log files** - Multiple `/tmp/clio_*_debug.log` files. Remove or consolidate
- [ ] **Print statements** - Check for any `print()` calls that should be logging
- [ ] **Commented code** - Remove dead code and old comments

## 📊 Metrics to Gather

Before making changes, measure:
- [ ] Startup time (time to first render)
- [ ] First query latency (user types → "Thinking" appears)
- [ ] Message round-trip time (query → response displayed)
- [ ] Memory usage (baseline and after 100 messages)
- [ ] CPU usage during idle vs thinking vs tool execution

## 🎯 Quick Wins (Easy, High Impact)

1. **Cache `_get_colors()` result** - Called dozens of times, never changes
2. **Move datetime import to top** - Don't import on every chat() call
3. **Remove debug logging** - Clean up `/tmp/clio_*_debug.log` writes
4. **Consolidate RichMarkdown imports** - Import once at top
5. **Cache widget references** - Look up once, store in self

## 🔍 Investigation Questions

- Is the tool streaming panel actually improving UX? Or adding complexity?
- Do we need three separate message storage lists?
- Should we use a message queue for UI updates instead of direct writes?
- Can we lazy-load some widgets that aren't always needed?
- Is the resize handler re-render necessary or can Textual handle it?

## Notes

- **Python philosophy**: Simpler is better. Question every class, every abstraction.
- **Textual best practices**: Check official docs for recommended patterns
- **Profile before optimizing**: Use `cProfile` or `py-spy` to find actual bottlenecks
- **Benchmark**: Create test script that sends 50 messages and measures timing
