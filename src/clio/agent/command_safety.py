"""Command-safety classification for `execute_bash`.

Two layers:
  * is_blocked()        -- catastrophic commands that are refused outright.
  * is_readonly_command() -- known read-only commands that may auto-run without
                             asking for permission. Everything else is gated.

Both are conservative (fail safe): anything unrecognized is treated as unsafe.

Customizable per-user via ~/.clio/config.json, so nothing is hardcoded that a
user can't extend:

    {
      "permissions": {
        "extra_readonly_commands": ["mytool", "rg"],
        "extra_readonly_git_subcommands": ["worktree"],
        "extra_blocked_patterns": ["terraform destroy"]
      }
    }
"""
import re
from typing import Optional, Set, Tuple


# Commands that only read state -- safe to run without asking.
DEFAULT_READONLY_COMMANDS: Set[str] = {
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg",
    "find", "echo", "which", "type", "file", "stat", "du", "df", "date",
    "whoami", "id", "env", "printenv", "ps", "tree", "basename", "dirname",
    "realpath", "readlink", "diff", "cmp", "sort", "uniq", "cut", "column",
    "jq", "nl", "tac", "tr", "less", "more", "uname", "hostname", "uptime",
}

# git subcommands that only read (no history / working-tree mutation).
DEFAULT_READONLY_GIT_SUBCOMMANDS: Set[str] = {
    "status", "diff", "log", "show", "branch", "remote", "ls-files",
    "rev-parse", "describe", "blame", "shortlog", "config", "tag",
    "stash", "reflog", "whatchanged", "cat-file", "ls-tree", "name-rev",
}

# Catastrophic patterns refused outright (checked space-insensitively).
DEFAULT_BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf $HOME", "> /dev/sda",
    "mkfs.", "dd if=", ":(){ :|:& };:", "chmod -R 777 /",
    "/etc/passwd", "/etc/shadow", "curl | bash", "wget | sh",
]

# Shell features that can write, escalate, or hide a destructive command inside
# an otherwise-safe one -- if present, never auto-approve.
_UNSAFE_SHELL = (">", "<", "`", "$(", "${", "sudo", "&", "\n")

# Cache of user extras loaded from config (loaded once).
_extras_cache: Optional[Tuple[Set[str], Set[str], list]] = None


def _user_extras() -> Tuple[Set[str], Set[str], list]:
    """Load user customizations from config.json (cached). Never raises."""
    global _extras_cache
    if _extras_cache is not None:
        return _extras_cache
    extra_cmds: Set[str] = set()
    extra_git: Set[str] = set()
    extra_blocked: list = []
    try:
        from ..config.manager import ConfigManager
        perms = getattr(ConfigManager().load(), "permissions", None)
        if perms is not None:
            extra_cmds = set(getattr(perms, "extra_readonly_commands", []) or [])
            extra_git = set(getattr(perms, "extra_readonly_git_subcommands", []) or [])
            extra_blocked = list(getattr(perms, "extra_blocked_patterns", []) or [])
    except Exception:
        pass
    _extras_cache = (extra_cmds, extra_git, extra_blocked)
    return _extras_cache


def reset_cache() -> None:
    """Drop the cached config extras (e.g. after the user edits config)."""
    global _extras_cache
    _extras_cache = None


def is_blocked(command: str) -> Optional[str]:
    """Return the matched catastrophic pattern if the command is refused, else None."""
    _, _, extra_blocked = _user_extras()
    normalized = command.lower().replace(" ", "")
    for pattern in list(DEFAULT_BLOCKED_PATTERNS) + extra_blocked:
        if pattern.lower().replace(" ", "") in normalized:
            return pattern
    return None


def is_readonly_command(command: str) -> bool:
    """True if `command` is a known read-only shell command, safe to auto-run.

    Conservative by design: any chaining/redirect/substitution/sudo, or any
    unrecognized command in the pipeline, returns False so it gets gated.
    """
    if not command or not command.strip():
        return False
    if any(tok in command for tok in _UNSAFE_SHELL):
        return False

    extra_cmds, extra_git, _ = _user_extras()
    readonly_commands = DEFAULT_READONLY_COMMANDS | extra_cmds
    readonly_git = DEFAULT_READONLY_GIT_SUBCOMMANDS | extra_git

    # Each pipe/';'-separated segment's leading command must be read-only.
    for segment in re.split(r"[|;]", command):
        tokens = segment.split()
        if not tokens:
            continue
        cmd = tokens[0]
        if cmd == "git":
            sub = tokens[1] if len(tokens) > 1 else ""
            if sub not in readonly_git:
                return False
        elif cmd not in readonly_commands:
            return False
    return True
