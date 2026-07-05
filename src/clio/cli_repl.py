"""Line-based CLI interface (Claude Code style).

Renders to the terminal's normal scrollback buffer instead of an alternate
screen, and never captures the mouse. The upshot: native terminal text
selection, copy/paste, scrollback and search all "just work" everywhere
(including the VS Code / Cursor integrated terminal), which the previous
Textual TUI could not provide.

The agent core, providers, config, context, RAG, history and command layers
are reused unchanged -- only the UI layer is replaced.
"""
import asyncio
import getpass
import os
import sys
import time
from pathlib import Path

try:  # Unix-only; used for Escape-to-cancel key watching during a running query
    import termios
    import tty
except ImportError:  # pragma: no cover - non-Unix
    termios = None
    tty = None

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.key_binding import KeyBindings

from .agent.core import Agent, strip_thinking_tags
from .config.manager import ConfigManager
from .context.manager import ContextManager
from .commands.router import CommandRouter


class ClioCompleter(Completer):
    """Completes /commands at the start of a line and @file paths anywhere."""

    def __init__(self, commands):
        self.commands = commands  # list of command strings like "/help"

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Slash command completion (only when it's the first token)
        if text.startswith("/") and " " not in text:
            word = text
            for cmd in self.commands:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word))
            return

        # @file completion on the current @token
        at = text.rfind("@")
        if at != -1:
            frag = text[at + 1:]
            # Don't complete if there's whitespace after the @ token
            if " " not in frag and '"' not in frag:
                base = frag or "."
                try:
                    p = Path(base)
                    if base.endswith("/") or p.is_dir():
                        directory, prefix = (p, "")
                    else:
                        directory, prefix = (p.parent if str(p.parent) else Path("."), p.name)
                    for entry in sorted(Path(directory).iterdir()):
                        name = entry.name
                        if name.startswith(prefix):
                            suffix = "/" if entry.is_dir() else ""
                            yield Completion(
                                name + suffix,
                                start_position=-len(prefix),
                            )
                except (OSError, ValueError):
                    return


class ClioREPL:
    """A line-based read-eval-print loop driving the existing Agent."""

    def __init__(self, launch_dir: str, conversation_id=None):
        self.launch_dir = launch_dir
        self._resumed = conversation_id is not None
        # highlight=False stops Rich from auto-coloring numbers/paths in our text
        self.console = Console(highlight=False)
        # The logged-in user, used as the input prompt. getpass.getuser() works
        # cross-platform (the WSL/Linux user under WSL, the OS user elsewhere).
        try:
            self.username = getpass.getuser()
        except Exception:
            self.username = "you"
        self._streamed_any = False      # did the current turn stream any tokens?
        self._status = None             # animated "thinking..." spinner, while waiting
        self._t_start = None            # perf_counter when the current turn's request began
        self._t_first_token = None      # perf_counter when the first token arrived
        self._token_count = 0           # streamed chunks this turn (≈ tokens for Ollama)
        # Escape-to-cancel: while a query runs we watch stdin for ESC and cancel.
        self._cancel_event = None       # asyncio.Event set when ESC is pressed
        self._escape_armed = False      # is the stdin ESC watcher currently active?
        self._escape_old = None         # saved termios state to restore
        self._escape_fd = None
        self.config_manager = ConfigManager()
        self.context_manager = ContextManager(working_dir=launch_dir)
        self.auto_approve_session = False

        self.agent = Agent(
            self.config_manager,
            permission_callback=self.request_permission,
            tool_callback=self.on_tool_executed,
            conversation_id=conversation_id,
            token_callback=self.on_token,
        )

        # Slash command registry
        self.router = CommandRouter()
        self._register_commands()

        history_path = Path.home() / ".clio" / "repl_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        # Ctrl+C clears the input (box shrinks back to one line) when there's
        # text; on an empty box it aborts so the loop can do double-press exit.
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event):
            buf = event.current_buffer
            if buf.text:
                buf.text = ""
                event.app.renderer.erase()
            else:
                event.app.exit(exception=KeyboardInterrupt())

        # Re-trigger autocomplete after deleting a character (backspace/delete),
        # so suggestions keep narrowing instead of vanishing until you retype.
        def _recomplete(buf):
            if buf.text and not buf.complete_state:
                buf.start_completion(select_first=False)

        @kb.add("backspace")
        def _(event):
            buf = event.current_buffer
            buf.delete_before_cursor(count=event.arg)
            _recomplete(buf)

        @kb.add("delete")
        def _(event):
            buf = event.current_buffer
            buf.delete(count=event.arg)
            _recomplete(buf)

        # Resolved context window for the current model; None until the first
        # response resolves it (the toolbar shows a provisional value until then).
        self._ctx_window = None

        from prompt_toolkit.styles import Style
        self.session = PromptSession(
            history=FileHistory(str(history_path)),
            completer=ClioCompleter(list(self.router.commands.keys())),
            complete_while_typing=True,
            key_bindings=kb,
            # Blinking block cursor.
            cursor=CursorShape.BLINKING_BLOCK,
            # On submit, erase the input line; we echo it ourselves in the loop.
            erase_when_done=True,
            # Persistent context meter pinned below the input, Claude Code style.
            bottom_toolbar=self._context_toolbar,
            style=Style.from_dict({"bottom-toolbar": "noreverse"}),
        )
        self._should_exit = False

    # ----- command registration -------------------------------------------

    def _register_commands(self):
        r = self.router
        r.register("/help", self._cmd_help, "Show available commands")
        r.register("/model", self._cmd_model, "List or switch model: /model <provider> <model>")
        r.register("/files", self._cmd_files, "List files in context")
        r.register("/add", self._cmd_add, "Add a file/folder to context: /add <path>")
        r.register("/remove", self._cmd_remove, "Remove a file from context: /remove <path>")
        r.register("/clear", self._cmd_clear, "Clear conversation history")
        r.register("/compact", self._cmd_compact, "Summarize older history to free context")
        r.register("/usage", self._cmd_usage, "Show this month's token usage and spend")
        r.register("/config", self._cmd_config, "Show config file path")
        r.register("/exit", self._cmd_exit, "Exit clio")
        r.register("/quit", self._cmd_exit, "Exit clio")

    # ----- agent callbacks -------------------------------------------------

    def _render_diff(self, old: str, new: str, filename: str = "") -> None:
        """Print a colored unified diff (green +, red -, like git/Claude Code)."""
        import difflib
        diff = list(difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="",
        ))
        if not diff:
            return
        body = Text()
        for ln in diff:
            if ln.startswith("+++") or ln.startswith("---"):
                body.append(ln + "\n", style="bold")
            elif ln.startswith("@@"):
                body.append(ln + "\n", style="cyan")
            elif ln.startswith("+"):
                body.append(ln + "\n", style="green")
            elif ln.startswith("-"):
                body.append(ln + "\n", style="red")
            else:
                body.append(ln + "\n", style="dim")
        self.console.print(Panel(body, title=f"[bold]Diff: {filename}[/bold]",
                                 border_style="cyan", expand=False))

    async def request_permission(self, operation: str, details: str, diff_info: dict = None) -> bool:
        """Ask the user to approve a tool action. Returns True to allow.

        No prompt is on screen while the agent runs (sequential loop), so we can
        ask directly with a small y/n/a prompt.
        """
        if self.auto_approve_session or self.config_manager.load().preferences.auto_approve:
            return True

        # The thinking spinner is a rich Live display that holds the terminal; if
        # it keeps running, prompt_toolkit's y/n/a prompt can't render and this
        # call hangs (the spinner just spins forever). Stop it while we ask, then
        # resume it afterward for the tool-execution wait.
        spinner_was_running = self._status is not None
        if spinner_was_running:
            self._status.stop()

        # The Escape watcher holds stdin in cbreak mode during the query; release
        # it so prompt_toolkit can read the y/n/a answer, then re-arm afterward.
        esc_was_armed = self._escape_armed
        if esc_was_armed:
            self._disarm_escape()

        self.console.print()
        # Show a diff preview of the change when we have the data.
        if diff_info and "new" in diff_info:
            filename = diff_info.get("path", "").split("/")[-1] or "file"
            self._render_diff(diff_info.get("old", ""), diff_info.get("new", ""), filename)
        self.console.print(Panel(
            Text(details, style="yellow"),
            title=f"[bold]Permission: {operation}[/bold]",
            border_style="yellow",
            expand=False,
        ))
        # Esc at the permission prompt cancels the whole query (same as Esc during
        # generation). prompt_toolkit owns stdin here, so we bind Esc on the prompt
        # itself; it sets the cancel event, then we wait to be torn down.
        pkb = KeyBindings()

        @pkb.add("escape", eager=True)
        def _(event):
            if self._cancel_event is not None:
                self._cancel_event.set()
            event.app.exit(result="\x00ESC")

        try:
            answer = await self.session.prompt_async(
                "  Allow? [y]es / [n]o / [a]lways: ", key_bindings=pkb
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer == "\x00ESC" and self._cancel_event is not None:
            # A cancel is now in flight; block so the agent does no further work,
            # and let the canceller raise CancelledError here to unwind cleanly.
            await asyncio.sleep(3600)
            return False
        answer = (answer or "").strip().lower()
        if answer in ("a", "always"):
            self.auto_approve_session = True
            self.console.print("[bold green]✓ approved[/bold green] [dim](auto-approving for this session)[/dim]")
            allowed = True
        else:
            allowed = answer in ("y", "yes")
            if allowed:
                self.console.print("[bold green]✓ approved[/bold green]")
            else:
                self.console.print("[bold red]✗ denied[/bold red] [dim](command not run)[/dim]")

        # Re-arm the Escape watcher for the rest of the query.
        if esc_was_armed:
            self._arm_escape()
        # Resume the spinner for the tool-execution / next model wait.
        if spinner_was_running and not self._streamed_any:
            self._status.start()
        return allowed

    async def on_tool_executed(self, tool_name: str, arguments: dict, result: str) -> None:
        """Print a compact line when the agent runs a tool (or is blocked)."""
        arg_preview = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:3])
        if len(arg_preview) > 100:
            arg_preview = arg_preview[:100] + "..."
        # Stop the spinner while we print the tool line, then resume it so it
        # keeps spinning during the next turn's wait (until the response streams).
        if self._status is not None:
            self._status.stop()
        res = (result or "").strip().lower()
        if res.startswith("permission denied") or res.startswith("blocked"):
            self.console.print(f"[red]✗ {tool_name}[/red] [dim]({arg_preview}) — not run[/dim]")
        else:
            self.console.print(f"[dim cyan]→ {tool_name}[/dim cyan] [dim]({arg_preview})[/dim]")
        if self._status is not None and not self._streamed_any:
            self._status.start()

    async def on_token(self, token: str) -> None:
        """Stream the assistant's text live (Claude-style). The first token of a
        turn stops the spinner and prints the green 'clio ›' prefix."""
        if self._status is not None:
            self._status.stop()  # response is streaming; hide the spinner
        if not self._streamed_any:
            self._streamed_any = True
            self._t_first_token = time.perf_counter()  # latency to first token
            sys.stdout.write("\033[1;32mclio › \033[0m")
        self._token_count += 1
        sys.stdout.write(token)
        sys.stdout.flush()

    def _print_metrics(self, t_end: float, streamed: bool = True, response: str = "") -> None:
        """Print a compact, dim timing line under clio's response:
        time-to-first-token (the wait before output starts), token count,
        tokens/sec, and total wall time. Tokens are counted as streamed chunks,
        which is ~1 token each from Ollama; the non-streamed fallback estimates
        from word count and flags it with a tilde."""
        if self._t_start is None:
            return
        total = t_end - self._t_start
        if streamed and self._t_first_token is not None:
            ttft = self._t_first_token - self._t_start
            gen = max(t_end - self._t_first_token, 1e-6)
            tps = self._token_count / gen
            self.console.print(
                f"[dim]⏱ {ttft:.1f}s to first token · {self._token_count} tok · "
                f"{tps:.1f} tok/s · {total:.1f}s total[/dim]"
            )
        else:
            toks = len(response.split())
            tps = toks / total if total > 0 else 0.0
            self.console.print(
                f"[dim]⏱ {total:.1f}s total · ~{toks} tok · {tps:.1f} tok/s[/dim]"
            )

    def _ctx_meter_text(self) -> tuple[str, str]:
        """(style, text) for the persistent context bar shown under the input,
        e.g. ' ctx [████░░░░░░░░░░░░░░░░] 18% (5,900 / 32,768 tok) · model'.

        Sync by design (prompt_toolkit calls it on every redraw): reads the
        cached window; until the first response resolves it, falls back to the
        known-families table and marks the value provisional with '~'.
        """
        used = self.agent.context_usage()
        window = self._ctx_window
        provisional = ""
        if not window:
            from .agent.context_window import DEFAULT_CONTEXT_WINDOW, lookup_known_window
            window = lookup_known_window(self.agent.current_model) or DEFAULT_CONTEXT_WINDOW
            provisional = "~"
        pct = min(used / window * 100, 100.0)
        slots = 20
        filled = min(slots, round(pct / 100 * slots))
        bar = "█" * filled + "░" * (slots - filled)
        style = "fg:#666666" if pct < 70 else ("fg:ansiyellow" if pct < 90 else "fg:ansired")
        text = (
            f" ctx [{bar}] {pct:.0f}%{provisional} ({used:,} / {window:,} tok)"
            f" · {self.agent.current_model}"
        )
        return style, text

    def _context_toolbar(self):
        """bottom_toolbar callable for prompt_toolkit; never raises."""
        try:
            style, text = self._ctx_meter_text()
            return [(style, text)]
        except Exception:
            return []

    async def _refresh_ctx_window(self) -> None:
        """Resolve the current model's context window (post-response, when a
        local model is guaranteed loaded so Ollama reports its runtime size)."""
        try:
            self._ctx_window = await self.agent.get_context_window()
        except Exception:
            pass

    # ----- slash command handlers -----------------------------------------

    def _cmd_help(self, args: str) -> str:
        lines = ["[bold]Commands[/bold]"]
        for cmd, desc in self.router.get_all_commands():
            lines.append(f"  [cyan]{cmd}[/cyan]  {desc}")
        lines.append("")
        lines.append("[bold]Tips[/bold]")
        lines.append("  Reference files with [cyan]@path/to/file[/cyan]")
        lines.append("  Select text with your mouse and copy as usual -- no special mode needed")
        return "\n".join(lines)

    async def _cmd_model(self, args: str) -> str:
        config = self.config_manager.load()
        parts = args.split()
        if len(parts) == 2:
            provider, model = parts
            return await self._switch_and_report(provider, model)

        # No args: interactive arrow-key picker (falls back to a text list when
        # not attached to a terminal).
        options = []
        for name, pcfg in config.providers.items():
            for m in pcfg.models:
                options.append((name, m))
        if not options:
            return "[yellow]No models configured.[/yellow]"

        if sys.stdin.isatty() and sys.stdout.isatty():
            picked = await self._pick_model_interactive(options)
            if picked is None:
                return "[dim]Model unchanged.[/dim]"
            return await self._switch_and_report(*picked)

        # Non-interactive fallback: the original text listing
        lines = [f"Current: [green]{self.agent.current_model}[/green] @ {self.agent.current_provider_name}", ""]
        for name, pcfg in config.providers.items():
            host = pcfg.hostname or pcfg.baseURL or name
            lines.append(f"[bold]{name}[/bold] [dim]({host})[/dim]")
            for m in pcfg.models:
                lines.append(f"  {m}")
        lines.append("")
        lines.append("[dim]Switch with: /model <provider> <model>[/dim]")
        return "\n".join(lines)

    async def _switch_and_report(self, provider: str, model: str) -> str:
        try:
            await self.agent.switch_model(provider, model)
            # New model: window unknown until its first response resolves it.
            self._ctx_window = None
            return f"Switched to [green]{model}[/green] @ {provider}"
        except ValueError as e:
            return f"[red]{e}[/red]"

    async def _pick_model_interactive(self, options):
        """Inline up/down + Enter model picker. Returns (provider, model) or
        None if cancelled. Not full-screen — renders in place, preserving
        scrollback like the rest of the line-based UI."""
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style

        # Start on the current model if it's in the list.
        cur = (self.agent.current_provider_name, self.agent.current_model)
        sel = [options.index(cur)] if cur in options else [0]

        def render():
            frags = [("class:title", "Select a model  (↑/↓ move · Enter select · Esc cancel)\n\n")]
            for i, (prov, model) in enumerate(options):
                chosen = i == sel[0]
                marker = "❯ " if chosen else "  "
                live = "  ● current" if (prov, model) == cur else ""
                style = "class:sel" if chosen else "class:opt"
                frags.append((style, f"{marker}{prov} / {model}{live}\n"))
            return frags

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("c-p")
        @kb.add("k")
        def _(event):
            sel[0] = (sel[0] - 1) % len(options)

        @kb.add("down")
        @kb.add("c-n")
        @kb.add("j")
        def _(event):
            sel[0] = (sel[0] + 1) % len(options)

        @kb.add("enter")
        def _(event):
            event.app.exit(result=options[sel[0]])

        @kb.add("c-c")
        @kb.add("escape")
        @kb.add("q")
        def _(event):
            event.app.exit(result=None)

        app = Application(
            layout=Layout(HSplit([Window(FormattedTextControl(render), height=len(options) + 2)])),
            key_bindings=kb,
            style=Style.from_dict({
                "title": "bold",
                "sel": "reverse",
                "opt": "",
            }),
            full_screen=False,
            erase_when_done=True,
        )
        return await app.run_async()

    def _cmd_files(self, args: str) -> str:
        files = self.context_manager.list_files()
        if not files:
            return "No files in context. Add with /add <path> or @mention."
        return "Files in context:\n" + "\n".join(f"  {f}" for f in files)

    async def _cmd_add(self, args: str) -> str:
        if not args.strip():
            return "Usage: /add <path>"
        path = args.strip()
        if Path(path).is_dir():
            return await self.context_manager.add_folder(path)
        return await self.context_manager.add_file(path)

    def _cmd_remove(self, args: str) -> str:
        if not args.strip():
            return "Usage: /remove <path>"
        return self.context_manager.remove_file(args.strip())

    def _cmd_clear(self, args: str) -> str:
        self.agent.clear_history()
        self.context_manager.clear()
        return "Conversation history and context cleared."

    async def _cmd_compact(self, args: str) -> str:
        return await self.agent.compact(force=True)

    async def _cmd_usage(self, args: str) -> str:
        """Month-to-date spend from the local ledger, plus authoritative
        account totals from providers that expose a free endpoint."""
        from datetime import datetime

        db = self.agent.history_db
        month_rows = db.get_monthly_usage()
        today = db.get_today_usage()

        lines = [f"[bold]Usage — {datetime.now().strftime('%B %Y')}[/bold]"]
        if not month_rows:
            lines.append("  no usage recorded this month")
        total_cost = 0.0
        any_estimates = False
        for r in month_rows:
            total_cost += r["total_cost"]
            marker = "~" if r["has_estimates"] else ""
            note = f" [dim]({r['unknown_rows']} unpriced calls)[/dim]" if r["unknown_rows"] else ""
            lines.append(
                f"  {r['provider']}/{r['model']}: "
                f"{r['prompt_tokens']:,} in + {r['completion_tokens']:,} out"
                f" = {marker}${r['total_cost']:.4f}{note}"
            )
            any_estimates = any_estimates or r["has_estimates"]
        lines.append(f"  [bold]month total: {'~' if any_estimates else ''}${total_cost:.4f}[/bold]")
        lines.append(
            f"  today: {today['prompt_tokens']:,} in + "
            f"{today['completion_tokens']:,} out = ${today['total_cost']:.4f}"
        )
        if any_estimates:
            lines.append("  [dim]~ = includes estimated/unpriced rows (not provider-billed)[/dim]")

        # Authoritative account totals where a free endpoint exists
        config = self.config_manager.load()
        orc = config.providers.get("openrouter")
        if orc and orc.apiKey and not orc.apiKey.startswith("PASTE"):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        "https://openrouter.ai/api/v1/credits",
                        headers={"Authorization": f"Bearer {orc.apiKey}"},
                    )
                    if resp.status_code == 200:
                        d = resp.json()["data"]
                        lines.append(
                            f"  OpenRouter account (authoritative, lifetime): "
                            f"${d.get('total_usage', 0):.4f} used of "
                            f"${d.get('total_credits', 0):.2f} credits"
                        )
            except Exception:
                lines.append("  [dim]OpenRouter account check unavailable[/dim]")
        if "anthropic" in config.providers:
            lines.append("  [dim]Anthropic billing: console.anthropic.com (no per-key spend API)[/dim]")
        return "\n".join(lines)

    def _cmd_config(self, args: str) -> str:
        return f"Config file: {self.config_manager.config_path}"

    def _cmd_exit(self, args: str) -> str:
        self._should_exit = True
        return "Goodbye."

    # ----- main loop -------------------------------------------------------

    def _print_welcome(self):
        c = self.console
        c.print()
        c.print(Panel(
            Text.from_markup(
                "[bold]CLIO[/bold] - self-hosted AI coding assistant\n\n"
                f"Model: [green]{self.agent.current_model}[/green] @ {self.agent.current_provider_name}\n"
                "Type [cyan]/help[/cyan] for commands, [cyan]/exit[/cyan] to quit.\n"
                "Text is natively selectable -- highlight and copy as usual."
            ),
            border_style="cyan",
            expand=False,
        ))
        c.print()

    def _print_resume_transcript(self):
        """On --continue, replay the loaded history as it appeared live
        (Claude Code style), so the user sees the chat they're resuming.

        Renders from agent.messages (the last <=20 reconstructed from the DB):
        user/assistant text styled like live turns, tool calls as dim markers,
        tool outputs skipped, compaction snapshots shown as a one-line notice.
        """
        msgs = getattr(self.agent, "messages", None)
        if not msgs:
            return
        from .agent.compaction import SUMMARY_ACK, is_summary_message
        from .agent.core import strip_thinking_tags

        c = self.console
        conv = {}
        try:
            conv = self.agent.history_db.get_conversation(self.agent.conversation_id) or {}
        except Exception:
            pass
        title = conv.get("title") or ""
        header = f"── resuming conversation #{self.agent.conversation_id}"
        if title:
            header += f" · {title}"
        c.print(f"[dim]{header} ──[/dim]")
        c.print()

        for m in msgs:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "user":
                if is_summary_message(m):
                    c.print("[dim](earlier conversation was compacted into a snapshot)[/dim]")
                    continue
                c.print(Text.assemble((f"{self.username} › ", "bold cyan"), (str(content), "")))
                c.print()
            elif role == "assistant":
                if content == SUMMARY_ACK:
                    continue
                for tc in m.get("tool_calls") or []:
                    name = (tc.get("function") or {}).get("name", "tool")
                    c.print(f"[dim]→ {name}[/dim]")
                text = strip_thinking_tags(str(content)) if content else ""
                if text:
                    c.print(Text.assemble(("clio › ", "bold green"), (text, "")))
                    c.print()
            # tool results are skipped: they're bulky and already reflected in
            # the assistant's replies

        c.print("[dim]── end of history · continue below ──[/dim]")
        c.print()

    def _print_memory_status(self):
        """Show at startup whether project memory (CLIO.md) was loaded, so it's
        visible that standing instructions are in effect this session."""
        from .agent.memory import discover_memory_files
        files = discover_memory_files(self.launch_dir)
        if files:
            total = 0
            for f in files:
                try:
                    total += len(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
            label = "file" if len(files) == 1 else "files"
            self.console.print(
                f"[green]✓ Project memory loaded[/green] "
                f"[dim]({len(files)} CLIO.md {label}, {total} chars)[/dim]"
            )
            for f in files:
                self.console.print(f"  [dim]• {f}[/dim]")
        else:
            self.console.print(
                "[dim]No CLIO.md project memory found — create one to add standing instructions.[/dim]"
            )
        self.console.print()

    def _arm_escape(self):
        """Start watching stdin for the Escape key so a running query can be
        cancelled. No-op if stdin isn't a TTY or termios is unavailable."""
        if self._escape_armed or termios is None or tty is None:
            return
        try:
            if not sys.stdin.isatty():
                return
            fd = sys.stdin.fileno()
            self._escape_old = termios.tcgetattr(fd)
            tty.setcbreak(fd)  # char-at-a-time, keeps ISIG so Ctrl+C still works
            asyncio.get_event_loop().add_reader(fd, self._on_escape_stdin)
            self._escape_fd = fd
            self._escape_armed = True
        except Exception:
            self._escape_armed = False

    def _disarm_escape(self):
        """Stop watching stdin and restore the terminal mode."""
        if not self._escape_armed:
            return
        try:
            asyncio.get_event_loop().remove_reader(self._escape_fd)
        except Exception:
            pass
        try:
            if self._escape_old is not None:
                termios.tcsetattr(self._escape_fd, termios.TCSADRAIN, self._escape_old)
        except Exception:
            pass
        self._escape_armed = False

    def _on_escape_stdin(self):
        """stdin reader callback: set the cancel event when ESC (0x1b) is seen."""
        try:
            data = os.read(self._escape_fd, 64)
        except Exception:
            return
        if b"\x1b" in data and self._cancel_event is not None:
            self._cancel_event.set()

    async def _await_cancellable(self, task, cancel_event):
        """Await `task`, but cancel it if `cancel_event` fires first.

        Returns (cancelled: bool, result). On cancel the task is awaited to let
        its CancelledError unwind cleanly before returning.
        """
        waiter = asyncio.create_task(cancel_event.wait())
        try:
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if cancel_event.is_set() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True, None
        return False, task.result()

    async def _handle_input(self, user_input: str):
        user_input = user_input.strip()
        if not user_input:
            return

        command, cmd_args, _ = self.router.parse(user_input)
        if command is not None:
            result = await self.router.execute(command, cmd_args)
            if result:
                self.console.print(result if "[" in result else Text(result))
            return

        # Regular message -> add @mentioned files to context, then chat
        mentions = self.router.extract_mentions(user_input)
        for m in mentions:
            res = await self.context_manager.add_file(m)
            if not res.startswith("Added"):
                self.console.print(f"[dim yellow]{res}[/dim yellow]")

        context = self.context_manager.format_context()

        self.console.print()
        # Animated "thinking..." spinner (same as the warm-up message) while we
        # wait. It's stopped the instant any output appears (first streamed token
        # or first tool call), so it sits just above clio's output / tool calls.
        self._streamed_any = False
        self._t_first_token = None
        self._token_count = 0
        self._t_start = time.perf_counter()
        self._status = self.console.status(
            "[dim]thinking…[/dim] [dim](esc to cancel)[/dim]", spinner="dots"
        )
        self._status.start()

        # Run the agent as a task and watch stdin for ESC so the user can cancel
        # mid-query and immediately type again.
        self._cancel_event = asyncio.Event()
        chat_task = asyncio.create_task(self.agent.chat(user_input, context=context))
        self._arm_escape()
        cancelled = False
        response = None
        try:
            cancelled, response = await self._await_cancellable(chat_task, self._cancel_event)
        finally:
            self._disarm_escape()
            self._cancel_event = None
            if self._status is not None:
                self._status.stop()
                self._status = None
        t_end = time.perf_counter()

        if cancelled:
            # Close the line if we were mid-stream, note the cancel, and keep the
            # conversation coherent (avoid two user messages in a row).
            if self._streamed_any:
                sys.stdout.write("\n")
                sys.stdout.flush()
            try:
                msgs = getattr(self.agent, "messages", None)
                if msgs and msgs[-1].get("role") == "user":
                    msgs.append({"role": "assistant", "content": "[cancelled by user]"})
            except Exception:
                pass
            self.console.print("[yellow]⎋ cancelled[/yellow] [dim](type a new message)[/dim]")
            self.console.print()
            return

        response = strip_thinking_tags(response or "")

        if self._streamed_any:
            # Already printed token-by-token; just finish the line.
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._print_metrics(t_end)
            await self._refresh_ctx_window()
            self.console.print()
        elif not response.strip():
            self.console.print("[bold green]clio ›[/bold green]")
            self.console.print()
        else:
            # Fallback (provider didn't stream): render as one atomic print.
            self.console.print(Text.assemble(("clio › ", "bold green"), (response, "")))
            self._print_metrics(t_end, streamed=False, response=response)
            await self._refresh_ctx_window()
            self.console.print()

    async def _preload_embeddings(self):
        """Warm the RAG embedding model at startup, with a visible spinner.

        The load is the ~5s one-time cost of bringing up the embedding model.
        We run it in an executor so the event loop stays free to animate the
        spinner, and mute OS fd 2 for the whole window so transformers' HF
        warning can't leak past the spinner's refresh thread (the concurrency
        that defeats a per-load mute). The spinner writes to stdout (fd 1), so
        muting fd 2 doesn't touch it.
        """
        try:
            retriever = getattr(self.agent.history_db, "_rag_retriever", None)
            if retriever is None:
                return
            em = retriever.embedding_manager
            if em.is_loaded():
                return
        except Exception:
            return  # RAG is optional; never block startup on it

        import sys
        try:
            stderr_fd = sys.stderr.fileno()
        except (AttributeError, ValueError, OSError):
            stderr_fd = 2
        saved_fd = os.dup(stderr_fd)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        loop = asyncio.get_event_loop()
        try:
            os.dup2(devnull_fd, stderr_fd)
            with self.console.status(
                "[dim]Warming up local model (one-time, a few seconds)...[/dim]",
                spinner="dots",
            ):
                await loop.run_in_executor(None, lambda: em.model)
        except Exception:
            pass
        finally:
            os.dup2(saved_fd, stderr_fd)
            os.close(saved_fd)
            os.close(devnull_fd)

        # Warm tiktoken too: its first get_encoding() loads BPE merges (~0.5s),
        # which otherwise blocks the event loop on the first message and stutters
        # the spinner. Done in an executor so startup stays responsive.
        try:
            def _warm_tiktoken():
                import tiktoken
                tiktoken.get_encoding("cl100k_base").encode("warm up")
            await loop.run_in_executor(None, _warm_tiktoken)
        except Exception:
            pass

    async def run(self):
        # Sequential loop: show the prompt, read a line, then process it while
        # NO prompt is on screen -- so the agent's response can stream cleanly to
        # the terminal (token by token) without a pinned prompt overwriting the
        # partial lines (which patch_stdout cannot avoid). Native copy/scrollback
        # are preserved since we never use the alternate screen.
        self._print_welcome()
        self._print_memory_status()
        if self._resumed:
            self._print_resume_transcript()
        await self._preload_embeddings()
        last_interrupt = 0.0
        while not self._should_exit:
            try:
                text = await self.session.prompt_async("› ")
            except KeyboardInterrupt:
                now = time.monotonic()
                if now - last_interrupt < 2.0:
                    self.console.print("[dim]Goodbye.[/dim]")
                    break
                last_interrupt = now
                self.console.print("[dim](press Ctrl+C again within 2s to exit)[/dim]")
                continue
            except EOFError:
                self.console.print("[dim]Goodbye.[/dim]")
                break
            text = (text or "").strip()
            if not text:
                continue
            # Echo the submitted line as the user's turn.
            self.console.print(
                Text.assemble((f"{self.username} › ", "bold cyan"), (text, ""))
            )
            try:
                await self._handle_input(text)
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")


def run_repl(launch_dir: str, conversation_id=None):
    """Entry point: build and run the line-based REPL."""
    repl = ClioREPL(launch_dir=launch_dir, conversation_id=conversation_id)
    asyncio.run(repl.run())
