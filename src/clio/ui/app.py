"""Main Textual UI application."""
import asyncio
import subprocess
import shutil
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Input, RichLog, Static, OptionList
from textual.widgets.option_list import Option
from textual.binding import Binding
from textual import events
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ..agent.core import Agent
from ..context.manager import ContextManager
from ..config.manager import ConfigManager
from ..commands.router import CommandRouter
from ..ide_bridge import get_bridge

try:
    from .file_autocomplete import FileAutoComplete
    HAS_AUTOCOMPLETE = True
except ImportError:
    HAS_AUTOCOMPLETE = False


class ChatApp(App):
    """CLIO chat application."""

    TITLE = "CLIO - Command Line Interactive Operator"

    CSS = """
    Screen {
        overflow-x: hidden;
        overflow-y: auto;
    }

    #chat-log {
        height: 1fr;
        width: 100%;
        max-width: 100%;
        border: solid $primary;
        padding: 1;
        overflow-x: hidden;
        overflow-y: auto;
    }

    #input-container {
        height: auto;
        width: 100%;
        max-width: 100%;
        padding: 1;
    }

    #status-bar {
        height: 1;
        width: 100%;
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    Input {
        width: 100%;
        max-width: 100%;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
    ]

    # Enable terminal text selection by not capturing mouse events
    # Users can hold Shift and select text with the mouse
    ENABLE_COMMAND_PALETTE = False
    
    def __init__(self, launch_dir: Optional[str] = None):
        """Initialize app."""
        super().__init__()

        # Store the working directory from when the app was launched
        self.launch_dir = launch_dir or os.getcwd()

        # Initialize components
        self.config_manager = ConfigManager()
        self.context_manager = ContextManager(working_dir=self.launch_dir)
        self.agent = Agent(self.config_manager, self.request_permission, self.on_tool_executed)
        self.command_router = CommandRouter()

        # Register commands
        self._register_commands()

        # IDE bridge will be connected on mount (when event loop is running)
        self._ide_bridge_connected = False

        # State
        self.pending_permission: Optional[asyncio.Future] = None
        self.last_assistant_response: str = ""
        self.conversation_history: List[Dict[str, str]] = []

        # Command history
        self.command_history: List[str] = []
        self.history_index: int = -1
    
    def compose(self) -> ComposeResult:
        """Compose UI."""
        yield Header()

        # Status bar
        yield Static(self._get_status_text(), id="status-bar")

        # Chat log
        yield RichLog(id="chat-log", wrap=True, markup=True)

        # Input with autocomplete
        with Container(id="input-container"):
            chat_input = Input(placeholder="Type a message or /help for commands...", id="chat-input")
            yield chat_input

            # Add autocomplete if available
            if HAS_AUTOCOMPLETE:
                yield FileAutoComplete(chat_input, Path(self.launch_dir))

        yield Footer()
    
    def _get_status_text(self) -> str:
        """Get status bar text."""
        config = self.config_manager.load()
        provider = self.agent.current_provider_name
        model = self.agent.current_model
        files_count = len(self.context_manager.list_files())
        tokens = self.context_manager.get_total_tokens()

        # Get hostname for display
        provider_config = config.providers.get(provider)
        if provider_config and provider_config.hostname:
            hostname = provider_config.hostname
        elif provider_config and provider_config.baseURL:
            hostname = provider_config.baseURL
        else:
            hostname = provider

        # Show current directory for @ mentions
        cwd_short = Path(self.launch_dir).name or self.launch_dir

        return f"🤖 {model} @ {hostname} | 📁 {files_count} files | 🔢 {tokens:,} tokens | 📂 {cwd_short}"

    async def _do_bridge_connect(self) -> None:
        """Async task to connect to IDE bridge."""
        try:
            bridge = get_bridge()
            connected = await bridge.connect()
            if connected:
                self._ide_bridge_connected = True
                chat_log = self.query_one("#chat-log", RichLog)
                chat_log.write("[green]✓ Connected to IDE - edits will appear in real-time![/green]")
        except Exception as e:
            # Silently fail - IDE bridge is optional
            pass

    def _register_commands(self) -> None:
        """Register slash commands."""
        self.command_router.register("/help", self._cmd_help)
        self.command_router.register("/clear", self._cmd_clear)
        self.command_router.register("/exit", self._cmd_exit)
        self.command_router.register("/model", self._cmd_model)
        self.command_router.register("/files", self._cmd_files)
        self.command_router.register("/add", self._cmd_add)
        self.command_router.register("/remove", self._cmd_remove)
        self.command_router.register("/config", self._cmd_config)
        self.command_router.register("/copy", self._cmd_copy)
        self.command_router.register("/export", self._cmd_export)
    
    def _cmd_help(self, args: str) -> str:
        """Show help."""
        return """**Available Commands:**

- `/help` - Show this help message
- `/model` - List and switch models
- `/clear` - Clear conversation history
- `/exit` - Exit the application
- `/files` - List files in context
- `/add <path>` - Add file or folder to context
- `/remove <path>` - Remove file from context
- `/config` - Show configuration
- `/copy` - Copy last assistant response to clipboard
- `/export [filename]` - Export conversation to markdown file

**@-mentions:**
- `@filename` - Reference a file (will be added to context)
- `@"path with spaces"` - Reference path with spaces

**Text Selection:**
- Hold **Shift** and drag with mouse to select text
- Then use Ctrl+Shift+C (or Cmd+C on Mac) to copy

**Examples:**
- `Add error handling to @auth.py`
- `/add src/`
- `/model` to switch models
- `/copy` to copy last response
- `/export my-chat.md` to save conversation
"""
    
    def _cmd_clear(self, args: str) -> str:
        """Clear conversation."""
        self.agent.clear_history()
        self.conversation_history.clear()
        self.last_assistant_response = ""
        return "✓ Cleared conversation history"
    
    def _cmd_exit(self, args: str) -> str:
        """Exit application."""
        self.exit()
        return "Goodbye!"
    
    async def _cmd_model(self, args: str) -> str:
        """List/switch models with numbered selection."""
        config = self.config_manager.load()

        # Build list of all available models
        model_options = []
        for provider_name, provider_config in config.providers.items():
            hostname = provider_config.hostname or provider_config.baseURL or provider_name
            for model in provider_config.models:
                is_current = (provider_name == self.agent.current_provider_name and
                            model == self.agent.current_model)
                marker = "●" if is_current else "○"
                display_text = f"{marker} {model} @ {hostname}"
                model_options.append((display_text, provider_name, model, is_current, hostname))

        # If args provided, try to switch by number
        if args.strip():
            try:
                selection = int(args.strip())
                if 1 <= selection <= len(model_options):
                    _, provider, model, _, hostname = model_options[selection - 1]
                    await self.agent.switch_model(provider, model)
                    return f"✓ Switched to {model} @ {hostname}"
                else:
                    return f"❌ Invalid selection. Choose 1-{len(model_options)}"
            except ValueError:
                return "❌ Invalid input. Use a number like `/model 2`"

        # Show numbered list
        lines = ["**Available Models:**\n"]
        for i, (display, provider, model, is_current, hostname) in enumerate(model_options, 1):
            lines.append(f"{i}. {display}")

        # Get current provider config for hostname
        current_provider_config = config.providers[self.agent.current_provider_name]
        current_hostname = current_provider_config.hostname or current_provider_config.baseURL or self.agent.current_provider_name

        lines.append(f"\n\n**Current:** {self.agent.current_model} @ {current_hostname}")
        lines.append("\n💡 Type `/model <number>` to switch (e.g., `/model 2`)")

        return "\n".join(lines)
    
    def _cmd_files(self, args: str) -> str:
        """List files in context."""
        files = self.context_manager.list_files()
        
        if not files:
            return "No files in context"
        
        tokens = self.context_manager.get_total_tokens()
        lines = [f"**Files in Context** ({len(files)} files, {tokens:,} tokens):\n"]
        
        for file_path in files:
            content = self.context_manager.get_file_content(file_path)
            file_tokens = self.context_manager.count_tokens(content)
            lines.append(f"  📄 {file_path} ({file_tokens:,} tokens)")
        
        return "\n".join(lines)
    
    async def _cmd_add(self, args: str) -> str:
        """Add file/folder to context."""
        if not args:
            return "Usage: /add <path>"
        
        path = args.strip()
        
        # Check if it's a directory
        if Path(path).is_dir():
            return await self.context_manager.add_folder(path)
        else:
            return await self.context_manager.add_file(path)
    
    def _cmd_remove(self, args: str) -> str:
        """Remove file from context."""
        if not args:
            return "Usage: /remove <path>"
        
        return self.context_manager.remove_file(args.strip())
    
    def _cmd_config(self, args: str) -> str:
        """Show config."""
        config = self.config_manager.load()
        return f"**Configuration:**\n\nConfig file: {self.config_manager.config_path}\n\n{config.model_dump_json(indent=2)}"

    def _cmd_copy(self, args: str) -> str:
        """Copy last assistant response to clipboard."""
        if not self.last_assistant_response:
            return "❌ No assistant response to copy"

        # Try to find clipboard utility
        clipboard_cmd = None
        if shutil.which("xclip"):
            clipboard_cmd = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            clipboard_cmd = ["xsel", "--clipboard", "--input"]
        elif shutil.which("pbcopy"):  # macOS
            clipboard_cmd = ["pbcopy"]
        elif shutil.which("wl-copy"):  # Wayland
            clipboard_cmd = ["wl-copy"]
        else:
            return "❌ No clipboard utility found (install xclip, xsel, wl-copy, or pbcopy)"

        try:
            subprocess.run(
                clipboard_cmd,
                input=self.last_assistant_response.encode(),
                check=True
            )
            return "✓ Copied last assistant response to clipboard"
        except subprocess.CalledProcessError as e:
            return f"❌ Failed to copy to clipboard: {e}"

    def _cmd_export(self, args: str) -> str:
        """Export conversation to markdown file."""
        if not self.conversation_history:
            return "❌ No conversation to export"

        # Generate filename
        if args.strip():
            filename = args.strip()
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"clio-chat-{timestamp}.md"

        # Ensure .md extension
        if not filename.endswith(".md"):
            filename += ".md"

        try:
            with open(filename, "w") as f:
                f.write("# CLIO Chat Export\n\n")
                f.write(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("---\n\n")

                for entry in self.conversation_history:
                    role = entry["role"]
                    content = entry["content"]

                    if role == "user":
                        f.write(f"## 👤 You\n\n{content}\n\n")
                    elif role == "assistant":
                        f.write(f"## 🤖 Assistant\n\n{content}\n\n")
                    elif role == "system":
                        f.write(f"## ⚙️ System\n\n{content}\n\n")

                    f.write("---\n\n")

            abs_path = Path(filename).absolute()
            return f"✓ Exported conversation to: {abs_path}"
        except Exception as e:
            return f"❌ Failed to export: {e}"
    
    def _create_panel(self, content, title="", border_style="blue"):
        """Create a panel that fits within the terminal width."""
        # Get terminal width, subtract padding and borders
        width = self.size.width - 6  # Account for padding and borders
        return Panel(content, title=title, border_style=border_style, width=width)

    async def on_mount(self) -> None:
        """Handle mount."""
        chat_log = self.query_one("#chat-log", RichLog)

        # Get session log path
        log_path = self.agent.session_logger.get_log_path()

        chat_log.write(self._create_panel(
            "[bold cyan]CLIO[/bold cyan] - Command Line Interactive Operator\n\n"
            "A self-hosted AI coding assistant.\n\n"
            f"📝 Session log: [dim]{log_path}[/dim]\n\n"
            "Type [bold]/help[/bold] for commands or start chatting!",
            title="Welcome"
        ))

        # Try to connect to IDE bridge (now that event loop is running)
        asyncio.create_task(self._do_bridge_connect())

        # Focus input
        self.query_one("#chat-input", Input).focus()

    async def on_key(self, event: events.Key) -> None:
        """Handle key presses for command history."""
        chat_input = self.query_one("#chat-input", Input)

        # Only handle arrow keys when input is focused
        if not chat_input.has_focus:
            return

        if event.key == "up":
            # Cycle backward through history
            if self.command_history:
                if self.history_index == -1:
                    # Save current input before navigating history
                    self.current_draft = chat_input.value
                    self.history_index = len(self.command_history) - 1
                elif self.history_index > 0:
                    self.history_index -= 1

                chat_input.value = self.command_history[self.history_index]
                chat_input.cursor_position = len(chat_input.value)
                event.prevent_default()

        elif event.key == "down":
            # Cycle forward through history
            if self.command_history and self.history_index != -1:
                if self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    chat_input.value = self.command_history[self.history_index]
                else:
                    # Return to draft or empty
                    self.history_index = -1
                    chat_input.value = getattr(self, 'current_draft', '')

                chat_input.cursor_position = len(chat_input.value)
                event.prevent_default()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        user_input = event.value.strip()

        if not user_input:
            return

        # Add to command history (avoid duplicates of last command)
        if not self.command_history or self.command_history[-1] != user_input:
            self.command_history.append(user_input)

        # Reset history navigation
        self.history_index = -1
        self.current_draft = ""

        # Clear input
        event.input.value = ""

        # Show user message
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(self._create_panel(user_input, title="[bold cyan]You[/bold cyan]", border_style="cyan"))

        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_input})

        # Parse command or message
        command, args, original = self.command_router.parse(user_input)

        if command:
            # Execute command
            result = await self.command_router.execute(command, args)
            chat_log.write(self._create_panel(Markdown(result), title="[bold green]System[/bold green]", border_style="green"))

            # Add system message to history
            self.conversation_history.append({"role": "system", "content": result})
        else:
            # Extract @mentions
            mentions = self.command_router.extract_mentions(user_input)

            # Add mentioned files to context
            for mention in mentions:
                result = await self.context_manager.add_file(mention)
                if not result.startswith("✓"):
                    chat_log.write(f"[yellow]{result}[/yellow]")

            # Get context
            context = self.context_manager.format_context()

            # Send to agent
            chat_log.write("[dim]Thinking...[/dim]")

            try:
                response = await self.agent.chat(user_input, context)
                chat_log.write(self._create_panel(Markdown(response), title="[bold magenta]Assistant[/bold magenta]", border_style="magenta"))

                # Save last response and add to history
                self.last_assistant_response = response
                self.conversation_history.append({"role": "assistant", "content": response})
            except Exception as e:
                # Get full traceback
                tb = traceback.format_exc()
                error_msg = f"**Error:**\n```\n{str(e)}\n\n{tb}\n```"
                chat_log.write(self._create_panel(Markdown(error_msg), title="[bold red]Error[/bold red]", border_style="red"))

                # Add error to history
                self.conversation_history.append({"role": "system", "content": f"Error: {str(e)}"})

        # Update status
        status_bar = self.query_one("#status-bar", Static)
        status_bar.update(self._get_status_text())
    
    async def request_permission(self, operation: str, details: str) -> bool:
        """Request permission from user."""
        # For now, auto-approve based on config
        config = self.config_manager.load()

        if config.preferences.auto_approve:
            return True

        # TODO: Implement interactive permission prompt
        # For now, just log and approve
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(f"[yellow]⚠️  {operation}: {details}[/yellow]")

        return True

    async def on_tool_executed(self, tool_name: str, arguments: dict, result: str) -> None:
        """Handle tool execution notification."""
        chat_log = self.query_one("#chat-log", RichLog)

        # Format tool call nicely
        if tool_name == "edit_file":
            path = arguments.get("path", "unknown")
            old_len = len(arguments.get("old_text", ""))
            new_len = len(arguments.get("new_text", ""))
            tool_display = f"🔧 **edit_file**: {path} (replaced {old_len} chars with {new_len} chars)"
        elif tool_name == "write_file":
            path = arguments.get("path", "unknown")
            content_len = len(arguments.get("content", ""))
            tool_display = f"✍️  **write_file**: {path} ({content_len} chars)"
        elif tool_name == "read_file":
            path = arguments.get("path", "unknown")
            tool_display = f"📖 **read_file**: {path}"
        elif tool_name == "execute_bash":
            command = arguments.get("command", "unknown")
            tool_display = f"💻 **execute_bash**: `{command}`"
        elif tool_name == "list_directory":
            path = arguments.get("path", ".")
            tool_display = f"📁 **list_directory**: {path}"
        else:
            tool_display = f"🔧 **{tool_name}**: {arguments}"

        # Show result
        result_preview = result[:200] + "..." if len(result) > 200 else result

        # Create panel with tool execution info
        tool_info = f"{tool_display}\n\n**Result:**\n{result_preview}"
        chat_log.write(self._create_panel(
            Markdown(tool_info),
            title="[bold yellow]Tool Execution[/bold yellow]",
            border_style="yellow"
        ))
    
    def action_clear(self) -> None:
        """Clear chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        self.agent.clear_history()
        self.conversation_history.clear()
        self.last_assistant_response = ""
