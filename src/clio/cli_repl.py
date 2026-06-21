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
import os
import time
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

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

    async def request_permission(self, operation: str, details: str, diff_info: dict = None) -> bool:
        """Ask the user to approve a tool action. Returns True to allow."""
        if self.auto_approve_session or self.config_manager.load().preferences.auto_approve:
            return True

        self.console.print()
        self.console.print(Panel(
            Text(details, style="yellow"),
            title=f"[bold]Permission: {operation}[/bold]",
            border_style="yellow",
            expand=False,
        ))
        answer = await self.session.prompt_async("  Allow? [y]es / [n]o / [a]lways: ")
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
        with self.console.status("[dim]thinking...[/dim]", spinner="dots"):
            response = await self.agent.chat(user_input, context=context)

        response = strip_thinking_tags(response or "")
        self.console.print(Rule(style="dim"))
        if response.strip():
            self.console.print(Markdown(response))
        self.console.print(Rule(style="dim"))
        self.console.print()

    async def run(self):
        self._print_welcome()
        last_interrupt = 0.0
        with patch_stdout():
            while not self._should_exit:
                try:
                    user_input = await self.session.prompt_async("clio › ")
                except KeyboardInterrupt:
                    # Double Ctrl+C within 2s exits; a single one just cancels the line.
                    # (Ctrl+Q is reserved by the Cursor/VS Code terminal, so we don't use it.)
                    now = time.monotonic()
                    if now - last_interrupt < 2.0:
                        self.console.print("[dim]Goodbye.[/dim]")
                        break
                    last_interrupt = now
                    self.console.print("[dim](press Ctrl+C again within 2s to exit)[/dim]")
                    continue
                except EOFError:
                    # Ctrl+D exits cleanly
                    self.console.print("[dim]Goodbye.[/dim]")
                    break
                try:
                    await self._handle_input(user_input)
                except KeyboardInterrupt:
                    # Ctrl+C during a response cancels the turn, not the app
                    self.console.print("\n[dim yellow]Cancelled.[/dim yellow]\n")
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/red]")


def run_repl(launch_dir: str, conversation_id=None):
    """Entry point: build and run the line-based REPL."""
    repl = ClioREPL(launch_dir=launch_dir, conversation_id=conversation_id)
    asyncio.run(repl.run())
