# RAG-Based Context Window Management

## Problem
Long coding sessions (200-500+ messages, 4-6 hours) exceed context windows and lose critical context about:
- Architectural decisions made hours ago
- Files touched across the codebase
- Patterns and conventions established earlier
- Bug fixes and their reasoning

## Why Not LLM Summarization?
Research shows:
- **20-30% hallucination rate** in dialogue summarization (Berkeley AI Research)
- **9-30% information loss** even with multi-level compression
- **Not free** - requires API calls every 50 messages
- **Lossy** - can't retrieve exact past discussions

## Solution: Local RAG + Hybrid Context

### Architecture
```
┌─────────────────────────────────────────┐
│ System Prompt (always)                  │
├─────────────────────────────────────────┤
│ Metadata (regex extraction)             │
│ - Files: [auth.py, config.json]         │
│ - Tools used: [edit_file, execute_bash] │
├─────────────────────────────────────────┤
│ RAG Retrieved (5-10 relevant chunks)    │
│ - Semantic search on user query         │
│ - From anywhere in conversation history │
├─────────────────────────────────────────┤
│ Recent Messages (last 15-20 verbatim)   │
│ - No information loss                   │
└─────────────────────────────────────────┘
```

### Technology Stack
- **Embeddings**: `all-MiniLM-L6-v2` (22MB, 100% offline, 5-14k sentences/sec)
- **Vector DB**: ChromaDB (lightweight, local)
- **Cost**: Free after one-time 22MB download
- **Provider**: Agnostic - works with any LLM

### Benefits
✅ **52% fewer hallucinations** vs summarization
✅ **Lossless** - retrieves exact messages
✅ **100% free** - no API costs
✅ **Offline** - works without internet
✅ **Provider agnostic** - not tied to OpenAI
✅ **Privacy** - embeddings stay local

## Implementation Plan

### Phase 1: Basic RAG (2-3 hours)
1. Add dependencies: `sentence-transformers`, `chromadb`
2. Create `rag/embeddings.py` - embed messages on save
3. Create `rag/retriever.py` - semantic search
4. Update `agent/core.py` - build hybrid context

### Phase 2: Metadata Tracking (1 hour)
1. Extract files from tool calls
2. Extract bash commands from tool results
3. Track in separate metadata table

### Phase 3: Optimization (1 hour)
1. Background embedding (async)
2. Caching for repeated queries
3. Fallback to sliding window if RAG unavailable

### Phase 4: User Controls (1 hour)
1. `/compact` - manual summarization (optional)
2. `--no-rag` - disable RAG, use sliding window
3. Show context stats in UI

## Files to Create
- `src/clio/rag/__init__.py`
- `src/clio/rag/embeddings.py`
- `src/clio/rag/retriever.py`
- `src/clio/rag/metadata.py`

## Files to Modify
- `pyproject.toml` - add dependencies
- `src/clio/agent/core.py` - hybrid context building
- `src/clio/history/database.py` - store embeddings

## Context Window Budget (Target: ~8K tokens)
- System prompt: 200 tokens
- Metadata: 300 tokens
- RAG retrieved (10 chunks): 2500 tokens
- Recent messages (20): 5000 tokens
**Total: ~8K tokens** (vs 50K+ without RAG)

## Success Metrics
- Load 500-message conversation in <2 seconds
- Retrieve relevant context from hours ago
- Work 100% offline
- Zero API costs for context management
