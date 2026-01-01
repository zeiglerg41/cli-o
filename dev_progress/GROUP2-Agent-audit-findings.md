# GROUP 2: Agent Core + Tools - Audit Findings

**Files audited:**
- `src/clio/agent/core.py` (513 lines)
- `src/clio/agent/tools.py` (740 lines)
- `src/clio/agent/session_logger.py` (104 lines)

---

## 🔴 CRITICAL ISSUES (Fix Now)

### 1. Blocking HTTP Calls in /usage Command ✅ FIXED

**Location:** `billing/openai_billing.py` lines 76, 165 + `app.py` line 858

**Problem:**
```python
with httpx.Client(timeout=30.0) as client:  # ❌ BLOCKING!
    response = client.get(url, headers=headers, params=params)
```

**Impact:** UI freezes for up to 30 seconds when typing `/usage` (waits for OpenAI billing API)

**Fix:** ✅ Changed to async:
- `httpx.Client` → `httpx.AsyncClient`
- Made `fetch_openai_costs()` and `fetch_openai_usage()` async
- Made `_cmd_usage()` async in app.py
- CommandRouter already handles async commands properly

**Result:** `/usage` command now runs without freezing UI

---

### 2. Debug Logging in Message Reconstruction (6 writes per conversation load)

**Location:** core.py lines 150-206 (`_reconstruct_messages` method)

**Problem:**
```python
with open("/tmp/clio_reconstruct_debug.log", "w") as f:
    f.write(f"=== RECONSTRUCTING {len(db_messages)} MESSAGES ===\n")
    # ... more writes on every iteration
```

**Impact:** Disk I/O on every conversation resume. For 20 messages = 20+ file writes.

**Fix:** DELETE all 6 debug log writes from `_reconstruct_messages()`.

**Savings:** Eliminate disk I/O when resuming conversations.

---

### 3. DateTime Import in Hot Path (Every chat() call)

**Location:** core.py line 333

**Problem:**
```python
async def chat(self, user_message: str, context: str = "") -> str:
    # ...
    from datetime import datetime  # ❌ Imported on EVERY message!
    current_date = datetime.now().strftime("%B %d, %Y")
```

**Why it's bad:**
- `chat()` is called on every user message
- Import overhead is unnecessary (though small)
- Violates PEP 8 (imports at top)

**Fix:** Move import to top of file, calculate date once in `__init__`:
```python
# At top of file:
from datetime import datetime

# In __init__:
self.current_date = datetime.now().strftime("%B %d, %Y")

# In chat():
system_prompt_with_date = f"{self.system_prompt}\n\nCurrent date: {self.current_date}"
```

**Alternative (if date must be fresh):** Import at top, calculate in chat() - but remove the import statement.

**Savings:** Cleaner code, slightly faster chat() calls.

---

## 🟡 MEDIUM ISSUES (Should Fix)

### 4. Fire-and-Forget asyncio.create_task() May Suppress Errors

**Location:** core.py lines 313-318

**Problem:**
```python
asyncio.create_task(self._save_message_with_rag(
    conversation_id=self.conversation_id,
    role="user",
    content=user_message
))
```

**Why questionable:**
- Exceptions in background tasks are swallowed silently
- No way to know if message saving failed

**Current mitigation:** `_save_message_with_rag` has try/except with logging.

**Assessment:** Probably okay as-is since errors are logged. No action needed unless errors appear in production.

---

### 5. get_tool_definitions() Returns Large Dict (207 lines)

**Location:** tools.py lines 514-720

**Problem:** Method returns a hardcoded 200+ line dict of tool schemas.

**Why it might be okay:**
- Called once per chat iteration (not per keystroke)
- Necessary for API format
- No obvious duplication (each tool has unique schema)

**Possible optimization:** Return cached dict instead of rebuilding every time.
```python
def __init__(self):
    # ...
    self._tool_definitions = self._build_tool_definitions()

def get_tool_definitions(self):
    return self._tool_definitions
```

**Assessment:** Low priority. Only optimize if profiling shows it's a bottleneck.

---

## 🟢 MINOR ISSUES (Nice to Have)

### 6. session_logger.py is Clean

**Status:** ✅ No issues found

The file is well-structured:
- Simple initialization
- Clear purpose
- No unnecessary complexity
- Good use of logging module

**No changes needed.**

---

### 7. tools.py Methods are Well-Organized

**Status:** ✅ Mostly good

Each tool method:
- Has single responsibility
- Uses async/await properly
- Handles errors with try/except
- Returns string results

**Possible micro-optimizations:**
- Some methods use `Path(path).resolve()` repeatedly - could cache
- Permission checking pattern is duplicated - but it's only 1 line, not worth abstracting

**Assessment:** Don't over-optimize. Code is readable and maintainable.

---

## 📊 Summary by the Numbers

| Issue | Lines Saved | Performance Gain |
|-------|-------------|------------------|
| ✅ Fix blocking HTTP in /usage | ~0 lines (refactor) | **UI no longer freezes for 30s** |
| Remove debug logging (6 writes) | ~50 lines | Eliminate disk I/O on conversation load |
| Move datetime import to top | ~0 lines (refactor) | Cleaner code, PEP 8 compliant |
| Cache tool definitions (optional) | ~0 lines (refactor) | Minimal gain, low priority |

**Total potential:** ~50 lines removed, cleaner imports, **major UX improvement**

---

## 🎯 Recommended Action Plan

### Phase 1: Quick Wins (15 min)
1. ✅ **DONE:** Fix blocking HTTP in /usage command - made async
2. ⏸️ Remove ALL debug logging from `_reconstruct_messages()`
3. ⏸️ Move datetime import to top of core.py
4. ⏸️ Calculate current_date once (either in __init__ or keep in chat() but use top-level import)

### Phase 2: Optional Optimizations (30 min)
5. ⏸️ Cache tool_definitions dict (only if needed)
6. ⏸️ Profile chat() method to find actual bottlenecks

---

## Questions for User

1. **Current date caching:** Should date be calculated once at startup, or fresh on every message?
   - Once at startup = faster but date won't change if session runs past midnight
   - Fresh every message = accurate but slightly slower

2. **Tool definitions caching:** Worth optimizing? Or is it premature?

---

## Notes

- **core.py** is generally well-structured. Main issues are debug logs and import placement.
- **tools.py** is large (740 lines) but each method is focused. The 207-line tool schema is necessary.
- **session_logger.py** is excellent - no changes needed.
- Total GROUP 2 savings: ~50 lines, cleaner imports, eliminate disk I/O

---

## Implementation Priority

**HIGH:**
1. Remove debug logging from _reconstruct_messages (blocking issue)
2. Move datetime import to top (code quality)

**LOW:**
3. Cache tool definitions (optional optimization)
