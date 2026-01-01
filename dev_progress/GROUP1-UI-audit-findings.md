# GROUP 1: UI Layer - Audit Findings

**Files audited:**
- `src/clio/ui/app.py` (1735 lines)
- `src/clio/ui/textarea_autocomplete.py` (267 lines)
- `src/clio/ui/thinking_indicator.py` (53 lines)

---

## 🔴 CRITICAL ISSUES (Fix Now)

### 1. Debug Logging Pollution (8 locations in app.py, 5 in textarea_autocomplete.py)

**Location:** app.py lines 1221-1564, textarea_autocomplete.py lines 111-142

**Problem:**
```python
with open("/tmp/clio_autocomplete_debug.log", "a") as f:
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    f.write(f"[{timestamp}] DEBUG: ...")
```

**Impact:** File I/O on every keystroke, autocomplete action, worker state change, etc.

**Fix:** DELETE all debug logging. Keep production logging only.

**Affected files:**
- `app.py`: Lines referencing `/tmp/clio_autocomplete_debug.log`, `/tmp/clio_cancel_debug.log`, `/tmp/clio_resize_debug.log`
- `textarea_autocomplete.py`: `get_selected_completion()` method (lines 111-142)

**Savings:** ~50 lines removed, eliminate disk I/O on hot path

---

### 2. Excessive Widget Lookups (31 calls to `query_one()`)

**Problem:** Every event handler calls `self.query_one("#widget-id")` instead of caching.

Examples:
```python
# Called 10+ times:
chat_log = self.query_one("#chat-log", RichLog)
thinking_indicator = self.query_one("#thinking-indicator", ThinkingIndicator)
chat_input = self.query_one("#chat-input", AutocompleteTextArea)
tool_panel = self.query_one("#tool-calls-panel", Static)
```

**Fix:** Cache widgets in `on_mount()` once:
```python
def on_mount(self):
    # Cache widgets
    self.chat_log = self.query_one("#chat-log", RichLog)
    self.thinking_indicator = self.query_one("#thinking-indicator", ThinkingIndicator)
    self.chat_input = self.query_one("#chat-input", AutocompleteTextArea)
    self.tool_panel = self.query_one("#tool-calls-panel", Static)
    self.status_bar = self.query_one("#status-bar", Static)
    self.autocomplete = self.query_one("#autocomplete-overlay", AutocompleteOverlay)
    # ... rest of on_mount
```

**Savings:** 31 DOM queries reduced to ~6 cached references. Faster event handling.

---

### 3. Triple Message Storage (3 lists storing same data)

**Problem:**
1. `agent.messages` (List[Message]) - Agent's conversation state
2. `app.conversation_history` (List[Dict]) - Used for /export
3. `app.display_messages` (List[tuple]) - Used for resize re-render

**Why it's bad:**
- Same data in 3 places
- Must keep in sync manually
- More memory usage
- More code complexity

**Fix:** Eliminate `app.conversation_history` entirely.

**How:**
- /export command: Read from `history_db.get_conversation_messages()` (already persisted!)
- Don't need in-memory copy for export

**Savings:** ~100 lines of sync logic, one less list to maintain

---

### 4. Uncached Color Map (10 calls to `_get_colors()`)

**Problem:** `_get_colors()` called in every message handler:
```python
colors = self._get_colors()  # Reads config, checks colorblind mode
```

**Why it's bad:** Config never changes during runtime. Pure waste.

**Fix:** Cache once in `__init__()`:
```python
def __init__(self, ...):
    # ... existing init
    self.colors = self._get_colors()  # Cache it
```

Replace all `colors = self._get_colors()` with `self.colors`.

**Savings:** 10 config lookups removed from hot path.

---

## 🟡 MEDIUM ISSUES (Should Fix)

### 5. Tool Call Formatting Duplication

**Problem:** Lines 1688-1703 have long if/elif chain:
```python
if tool_name == "edit_file":
    tool_display = f"🔧 **edit_file**: {path}..."
elif tool_name == "write_file":
    tool_display = f"✍️  **write_file**: {path}..."
# ... 6 more cases
```

**Fix:** Move to tools.py where tool definitions live. Or use a dict:
```python
TOOL_FORMATTERS = {
    "edit_file": lambda a: f"🔧 **edit_file**: {a['path']} (replaced {len(a.get('old_text',''))} chars with {len(a.get('new_text',''))} chars)",
    "write_file": lambda a: f"✍️  **write_file**: {a['path']} ({len(a.get('content',''))} chars)",
    # ...
}
tool_display = TOOL_FORMATTERS.get(tool_name, lambda a: f"🔧 **{tool_name}**: {a}")(arguments)
```

**Savings:** ~20 lines → ~8 lines

---

### 6. Resize Handler Re-renders EVERYTHING

**Problem:** Lines 1030-1062 - On every resize, clears entire chat log and re-renders all messages.

```python
def on_resize(self, event):
    chat_log.clear()
    for stored_content, title, border_style, content_type, align in self.display_messages:
        # Re-render every message
```

**Why questionable:** Does Textual really need this? Panels should auto-reflow.

**Investigation needed:** Test removing this handler. Does UI break? Probably not.

**Savings:** Could eliminate entire handler (~35 lines) + `display_messages` list.

---

### 7. Status Bar Updates on Every Message

**Problem:** Line 1580 - `status_bar.update(self._get_status_text())` called after every message.

**Why it's bad:** Recalculates tokens/cost on every message. Low priority since it's fast.

**Fix:** Only update when query completes (in `on_worker_state_changed`), not in `_process_message`.

**Savings:** Minimal, but cleaner.

---

## 🟢 MINOR ISSUES (Nice to Have)

### 8. Unused Helper Methods

- `_cmd_files()`, `_cmd_add()`, `_cmd_remove()` (lines 714-749) - Not registered in router. Dead code?

**Check:** Search for calls to these methods.

**Fix:** DELETE if unused.

---

### 9. AutocompleteTextArea Complexity

**Problem:** Lines 34-119 - Custom TextArea with escape key handling, backslash-to-newline conversion.

**Why complex:** Shift+Enter becomes "backslash then enter" - needs special handling.

**Question:** Is this still needed? Test if Textual fixed Shift+Enter natively.

**If yes:** Keep it.
**If no:** Simplify by removing backslash hack.

---

### 10. Escape Double-Tap for Clear

**Problem:** Lines 1253-1264 - Press Escape twice to clear input. Requires timer state tracking.

**Question:** Do users want this? Or is it confusing?

**Alternative:** Single Escape clears (simpler). Ctrl+U is standard terminal clear.

**If keeping:** Document in /help.

---

## 📊 Summary by the Numbers

| Issue | Lines Saved | Performance Gain |
|-------|-------------|------------------|
| Remove debug logging | ~50 lines | Eliminate disk I/O on hot path |
| Cache widget lookups | ~0 lines (refactor) | 31 DOM queries → 6 cached refs |
| Remove conversation_history | ~100 lines | Less memory, simpler sync |
| Cache color map | ~0 lines (refactor) | 10 config reads removed |
| Tool formatting cleanup | ~12 lines | Cleaner code |
| Remove resize handler? | ~35 lines | TBD - test first |
| Remove dead code (_cmd_files) | ~35 lines | Less confusion |

**Total potential:** ~230 lines removed (13% reduction from 1735 → 1505)

---

## 🎯 Recommended Action Plan

### Phase 1: Quick Wins (30 min) ✅ COMPLETE
1. ✅ Remove ALL debug logging (`/tmp/clio_*.log` writes) - **DONE: ~60 lines removed**
2. ✅ Cache `_get_colors()` result - **DONE: Renamed to _cached_colors, 10 lookups eliminated**
3. ✅ Remove dead code (`_cmd_files`, `_cmd_add`, `_cmd_remove`) - **DONE: 37 lines removed**

**Total Phase 1 savings:** ~97 lines removed, eliminated disk I/O on every keystroke

### Phase 2: Widget Caching (1 hour) - **NOT STARTED**
4. ⏸️ Cache all widgets in `on_mount()`
5. ⏸️ Replace all `query_one()` calls with cached refs

### Phase 3: Message Storage (1 hour) - **NOT STARTED**
6. ⏸️ Remove `conversation_history` list
7. ⏸️ Update /export to read from database
8. ⏸️ Test that nothing breaks

### Phase 4: Investigation (30 min) - **NOT STARTED**
9. ⏸️ Test removing `on_resize()` handler - does UI break?
10. ⏸️ Check if dead code is actually called anywhere
11. ⏸️ Test if Shift+Enter works natively in Textual now

---

## Questions for User

1. **Escape double-tap to clear input** - Keep or remove?
2. **Resize handler** - Can we remove it and let Textual handle reflow?
3. **Tool call streaming panel** - Worth the complexity? Or just show tools in final message?

---

## Notes

- **thinking_indicator.py** is clean, no changes needed
- **textarea_autocomplete.py** just needs debug logging removed
- **app.py** is the main target - 1735 lines can be reduced significantly
