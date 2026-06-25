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

        self.session = PromptSession(
            history=FileHistory(str(history_path)),
            completer=ClioCompleter(list(self.router.commands.keys())),
            complete_while_typing=True,
            key_bindings=kb,
            # Blinking block cursor.
            cursor=CursorShape.BLINKING_BLOCK,
            # On submit, erase the input line; we echo it ourselves in the loop.
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
        try:
            answer = await self.session.prompt_async("  Allow? [y]es / [n]o / [a]lways: ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
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
        self.console.print()

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
        self._status = self.console.status("[dim]thinking…[/dim]", spinner="dots")
        self._status.start()
        try:
            response = await self.agent.chat(user_input, context=context)
        finally:
            if self._status is not None:
                self._status.stop()
                self._status = None
        t_end = time.perf_counter()
        response = strip_thinking_tags(response or "")

        if self._streamed_any:
            # Already printed token-by-token; just finish the line.
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._print_metrics(t_end)
        elif not response.strip():
            self.console.print("[bold green]clio ›[/bold green]")
            self.console.print()
        else:
            # Fallback (provider didn't stream): render as one atomic print.
            self.console.print(Text.assemble(("clio › ", "bold green"), (response, "")))
            self._print_metrics(t_end, streamed=False, response=response)

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
