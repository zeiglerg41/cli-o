"""Persistent project memory for clio.

clio loads ``CLIO.md`` files into the system prompt each turn so project
conventions, architecture notes, and standing instructions survive across
sessions (clio's equivalent of Claude Code's CLAUDE.md, but clio-native only).

Discovery (later entries are more specific and appear last in the prompt, where
the model weights them most):

  1. Global  : ``~/.clio/CLIO.md``
  2. Project : each ``CLIO.md`` from the git root down to the current working
               directory. If the cwd isn't in a git repo, only the cwd's own
               ``CLIO.md`` is considered (we don't walk the whole filesystem).

A character budget guards against a huge memory file dominating the context.
"""
from pathlib import Path
from typing import List

MEMORY_FILENAME = "CLIO.md"
# Budget guard. ~16k chars ≈ 4k tokens; keeps memory from crowding out the
# conversation even on small local-model context windows.
MAX_MEMORY_CHARS = 16000


def _git_root(start: Path) -> Path | None:
    """Return the nearest ancestor (inclusive) containing a .git, else None."""
    for d in [start, *start.parents]:
        if (d / ".git").exists():
            return d
    return None


def discover_memory_files(working_dir: str) -> List[Path]:
    """Return the CLIO.md files to load, in load order (global first, then
    git-root → cwd so the most specific file is last). Deduplicated."""
    files: List[Path] = []

    global_file = Path.home() / ".clio" / MEMORY_FILENAME
    if global_file.is_file():
        files.append(global_file)

    try:
        cwd = Path(working_dir).expanduser().resolve()
    except Exception:
        return files

    root = _git_root(cwd)
    if root is not None:
        chain = [cwd]
        if cwd != root:
            for d in cwd.parents:
                chain.append(d)
                if d == root:
                    break
        project_dirs = list(reversed(chain))  # root first, cwd last
    else:
        project_dirs = [cwd]

    for d in project_dirs:
        f = d / MEMORY_FILENAME
        if f.is_file() and f not in files:
            files.append(f)
    return files


def load_project_memory(working_dir: str) -> str:
    """Load and concatenate CLIO.md memory for the system prompt.

    Returns a formatted string (each file under a ``## <path>`` header), or an
    empty string if there's nothing to load. Truncated to MAX_MEMORY_CHARS.
    """
    parts: List[str] = []
    for f in discover_memory_files(working_dir):
        try:
            text = f.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if text:
            parts.append(f"## {f}\n{text}")

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    if len(combined) > MAX_MEMORY_CHARS:
        combined = combined[:MAX_MEMORY_CHARS].rstrip() + "\n\n[... project memory truncated ...]"
    return combined
