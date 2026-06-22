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
import itertools
import os
import shutil
import time
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

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
        # highlight=False stops Rich from auto-coloring numbers/paths in our text
        self.console = Console(highlight=False)
        # The logged-in user, used as the input prompt. getpass.getuser() works
        # cross-platform (the WSL/Linux user under WSL, the OS user elsewhere).
        try:
            self.username = getpass.getuser()
        except Exception:
            self.username = "you"
        # Concurrent input/processing state (input box stays live while the
        # agent works; messages typed mid-response are queued).
        self._queue = None              # asyncio.Queue of pending user messages
        self._busy = False              # True while the agent is processing
        self._pending_permission = None # Future awaiting a y/n/a answer
        self._spinner_frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        self.config_manager = ConfigManager()
        self.context_manager = ContextManager(working_dir=launch_dir)
        self.auto_approve_session = False

        self.agent = Agent(
            self.config_manager,
            permission_callback=self.request_permission,
            tool_callback=self.on_tool_executed,
            conversation_id=conversation_id,
        )

        # Slash command registry
        self.router = CommandRouter()
        self._register_commands()

        history_path = Path.home() / ".clio" / "repl_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.session = PromptSession(
            history=FileHistory(str(history_path)),
            completer=ClioCompleter(list(self.router.commands.keys())),
            complete_while_typing=True,
            # reserve_space_for_menu=0 removes the ~8 rows prompt_toolkit reserves
            # under the input (that padding was making the box look tall). The
            # bottom line comes from bottom_toolbar, which keeps a row reserved
            # on-screen so the box's bottom border is never cut off at the edge.
            reserve_space_for_menu=0,
            style=Style.from_dict({"bottom-toolbar": "noreverse"}),
            # On submit, erase the whole input box (lines + arrow + text). We
            # then echo the message into the transcript and render the agent's
            # work above a fresh, empty input box -- so the box stays at the
            # bottom and nothing renders "inside" it.
            erase_when_done=True,
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

        We don't open a second prompt (that would clash with the always-live
        input box). Instead we print the request and await a Future that the
        input loop resolves with whatever the user types next (y / n / a).
        """
        if self.auto_approve_session or self.config_manager.load().preferences.auto_approve:
            return True

        self.console.print()
        # Show a diff preview of the change when we have the data.
        if diff_info and "new" in diff_info:
            filename = diff_info.get("path", "").split("/")[-1] or "file"
            self._render_diff(diff_info.get("old", ""), diff_info.get("new", ""), filename)
        self.console.print(Panel(
            Text(details, style="yellow"),
            title=f"[bold]Permission: {operation}[/bold]  —  answer below: y / n / a",
            border_style="yellow",
            expand=False,
        ))
        loop = asyncio.get_event_loop()
        self._pending_permission = loop.create_future()
        try:
            answer = await self._pending_permission
        except asyncio.CancelledError:
            answer = ""
        finally:
            self._pending_permission = None
        answer = (answer or "").strip().lower()
        if answer in ("a", "always"):
            self.auto_approve_session = True
            return True
        return answer in ("y", "yes")

    async def on_tool_executed(self, tool_name: str, arguments: dict, result: str) -> None:
        """Print a compact line when the agent runs a tool."""
        arg_preview = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:3])
        if len(arg_preview) > 100:
            arg_preview = arg_preview[:100] + "..."
        self.console.print(f"[dim cyan]→ {tool_name}[/dim cyan] [dim]({arg_preview})[/dim]")

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
            try:
                await self.agent.switch_model(provider, model)
                return f"Switched to [green]{model}[/green] @ {provider}"
            except ValueError as e:
                return f"[red]{e}[/red]"
        # List available
        lines = [f"Current: [green]{self.agent.current_model}[/green] @ {self.agent.current_provider_name}", ""]
        for name, pcfg in config.providers.items():
            host = pcfg.hostname or pcfg.baseURL or name
            lines.append(f"[bold]{name}[/bold] [dim]({host})[/dim]")
            for m in pcfg.models:
                lines.append(f"  {m}")
        lines.append("")
        lines.append("[dim]Switch with: /model <provider> <model>[/dim]")
        return "\n".join(lines)

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

    async def _handle_input(self, user_input: str):
        user_input = user_input.strip()
        if not user_input:
            return

        # Echo the submitted message into the transcript (the input box itself
        # was erased on submit). Rendered as Text so '[' isn't treated as markup.
        self.console.print(
            Text.assemble((f"{self.username} › ", "bold cyan"), (user_input, ""))
        )

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
        # No rich spinner here: the "working..." indicator lives in the input
        # box's bottom toolbar (see run()), so the input stays usable meanwhile.
        response = await self.agent.chat(user_input, context=context)

        response = strip_thinking_tags(response or "")
        # Label clio's turn with a "clio ›" prefix (the user's turn shows as "›").
        self.console.print("[bold green]clio ›[/bold green]", end=" ")
        if response.strip():
            self.console.print(Markdown(response))
        else:
            self.console.print()
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

    def _bottom_toolbar(self):
        """Bottom line of the input box; doubles as a live status indicator."""
        width = shutil.get_terminal_size((80, 24)).columns
        if self._pending_permission is not None and not self._pending_permission.done():
            return ANSI("\033[33m  awaiting permission — type  y  /  n  /  a\033[0m")
        if self._busy:
            frame = next(self._spinner_frames)
            queued = self._queue.qsize() if self._queue else 0
            extra = f"   ({queued} queued)" if queued else ""
            return ANSI(f"\033[2m{frame} working...{extra}\033[0m")
        return ANSI("\033[2m" + "─" * width + "\033[0m")

    async def run(self):
        # patch_stdout(raw=True) keeps the input box pinned at the bottom while
        # rich output streams above it, in the normal screen buffer (so native
        # copy/scrollback still work). raw=True passes rich's ANSI through
        # un-mangled. Two coroutines run concurrently: one always shows the input
        # box (so you can type/queue while the agent works), the other processes
        # the queue one message at a time.
        self._print_welcome()
        await self._preload_embeddings()
        self._queue = asyncio.Queue()

        async def input_loop():
            last_interrupt = 0.0
            while not self._should_exit:
                width = shutil.get_terminal_size((80, 24)).columns
                try:
                    text = await self.session.prompt_async(
                        ANSI("\033[2m" + "─" * width + "\033[0m\n› "),
                        bottom_toolbar=self._bottom_toolbar,
                        refresh_interval=0.1,  # animate the working... spinner
                    )
                except KeyboardInterrupt:
                    now = time.monotonic()
                    if now - last_interrupt < 2.0:
                        self._should_exit = True
                        self.console.print("[dim]Goodbye.[/dim]")
                        break
                    last_interrupt = now
                    self.console.print("[dim](press Ctrl+C again within 2s to exit)[/dim]")
                    continue
                except EOFError:
                    self._should_exit = True
                    self.console.print("[dim]Goodbye.[/dim]")
                    break
                text = (text or "").strip()
                if not text:
                    continue
                # If a permission request is open, this answer goes to it.
                if self._pending_permission is not None and not self._pending_permission.done():
                    self._pending_permission.set_result(text)
                    continue
                # Otherwise queue it for processing (echoed when it runs, so the
                # transcript stays in order; the toolbar shows the queued count).
                await self._queue.put(text)

        async def process_loop():
            while not self._should_exit:
                try:
                    text = await asyncio.wait_for(self._queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                self._busy = True
                try:
                    await self._handle_input(text)
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/red]")
                finally:
                    self._busy = False

        with patch_stdout(raw=True):
            inp = asyncio.create_task(input_loop())
            proc = asyncio.create_task(process_loop())
            await inp
            proc.cancel()
            try:
                await proc
            except asyncio.CancelledError:
                pass


def run_repl(launch_dir: str, conversation_id=None):
    """Entry point: build and run the line-based REPL."""
    repl = ClioREPL(launch_dir=launch_dir, conversation_id=conversation_id)
    asyncio.run(repl.run())
