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
from textual.widgets import Header, Footer, Input, TextArea, RichLog, Static, OptionList, Label
from textual.widgets.option_list import Option
from textual.binding import Binding
from textual import events
from textual.message import Message
from textual.screen import ModalScreen
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.console import Console
from rich.align import Align

from ..agent.core import Agent
from ..context.manager import ContextManager
from ..config.manager import ConfigManager
from ..commands.router import CommandRouter
from ..ide_bridge import get_bridge
from ..history.database import HistoryDatabase
from .textarea_autocomplete import AutocompleteOverlay


class AutocompleteTextArea(TextArea):
    """Custom TextArea that allows parent to handle Tab/Enter for autocomplete."""

    class AutocompleteKey(Message):
        """Message sent when Tab/Enter pressed during autocomplete."""
        def __init__(self, key: str) -> None:
            self.key = key
            super().__init__()

    class SubmitMessage(Message):
        """Message sent when Enter pressed (without Shift) to submit."""
        pass

    class EscapeKey(Message):
        """Message sent when Escape is pressed."""
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.autocomplete_visible = False
        self._just_handled_backslash = False  # Flag to ignore Enter after backslash

    async def on_key(self, event: events.Key) -> None:
        """Intercept Tab/Enter when autocomplete is visible, and Enter for submit."""
        # Debug ALL keys at widget level
        import datetime
        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] WIDGET on_key: key='{event.key}'\n")
            f.flush()

        # If autocomplete is visible and Tab/Enter pressed
        if self.autocomplete_visible and event.key in ("tab", "enter"):
            # Don't let TextArea handle it, send message to parent
            event.prevent_default()
            event.stop()
            self.post_message(self.AutocompleteKey(event.key))
            return

        # Handle Escape - prevent default focus change
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.EscapeKey())
            return

        # Shift+Enter comes through as backslash THEN enter - handle backslash
        if event.key == "backslash":
            event.prevent_default()
            event.stop()
            # Set flag to ignore the Enter that follows
            self._just_handled_backslash = True
            # Insert newline at cursor position
            cursor_location = self.cursor_location
            current_text = self.text
            lines = current_text.split('\n') if current_text else ['']
            row, col = cursor_location

            if row < len(lines):
                line = lines[row]
                # Split the line at cursor position
                before = line[:col]
                after = line[col:]
                lines[row] = before
                lines.insert(row + 1, after)
                self.text = '\n'.join(lines)
                # Move cursor to start of next line
                self.move_cursor((row + 1, 0))
            return

        # Plain Enter submits message (but ignore if it's the Enter after backslash)
        if event.key == "enter" and not self.autocomplete_visible:
            # Check if this is the Enter that follows a backslash (Shift+Enter)
            if self._just_handled_backslash:
                # This is Shift+Enter - ignore this Enter
                self._just_handled_backslash = False
                event.prevent_default()
                event.stop()
                return

            # Plain Enter - submit the message
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitMessage())
            return


try:
    from .file_autocomplete import FileAutoComplete
    from .command_autocomplete import CommandAutoComplete
    HAS_AUTOCOMPLETE = True
except ImportError:
    HAS_AUTOCOMPLETE = False

from .thinking_indicator import ThinkingIndicator


def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to relative time string like '2 hours ago'."""
    from datetime import datetime, timedelta

    dt = datetime.fromisoformat(iso_timestamp)
    now = datetime.now()
    diff = now - dt

    if diff < timedelta(minutes=1):
        return "just now"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif diff < timedelta(days=30):
        weeks = diff.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif diff < timedelta(days=365):
        months = diff.days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = diff.days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"


class HistorySelectScreen(ModalScreen[int]):
    """Modal screen for selecting a conversation to continue."""

    BINDINGS = [
        ("escape,q", "dismiss", "Cancel"),
    ]

    CSS = """
    HistorySelectScreen {
        align: center middle;
    }

    #history-dialog {
        width: 80;
        height: 25;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    #history-title {
        dock: top;
        height: 1;
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }

    #history-list {
        height: 1fr;
        border: solid $primary;
    }

    #history-help {
        dock: bottom;
        height: 1;
        content-align: center middle;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, conversations: List[Dict]):
        super().__init__()
        self.conversations = conversations

    def compose(self) -> ComposeResult:
        with Container(id="history-dialog"):
            yield Label("📜 Resume Conversation", id="history-title")

            # Build option list
            options = []
            for conv in self.conversations:
                conv_id = conv['id']
                time_ago = relative_time(conv['start_time'])
                msg_count = conv['message_count']
                title = conv['title'] or "New conversation"
                working_dir = Path(conv['working_dir']).name
                starred = "⭐ " if conv['starred'] else ""

                # Truncate title if too long
                max_title_len = 40
                display_title = title[:max_title_len]
                if len(title) > max_title_len:
                    display_title = display_title[:max_title_len-3] + "..."

                # Format: "• {title}  ({time} · {N} msgs · {dir})"
                option_text = f"• {starred}{display_title}  ({time_ago} · {msg_count} msgs · {working_dir})"

                options.append(Option(option_text, id=str(conv_id)))

            yield OptionList(*options, id="history-list")
            yield Label("↑/↓ to navigate • Enter to select • Esc/q to cancel", id="history-help")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        conv_id = int(event.option.id)
        self.dismiss(conv_id)

    def action_dismiss(self) -> None:
        """Dismiss without selection."""
        self.dismiss(None)


class ChatApp(App):
    """CLIO chat application."""

    TITLE = "CLIO - Command Line Interactive Operator"

    # Color mappings for normal and colorblind modes
    COLOR_MAPS = {
        "normal": {
            "user_color": "cyan",
            "user_title": "[bold cyan]You[/bold cyan]",
            "assistant_color": "magenta",
            "assistant_title": "[bold magenta]Clio[/bold magenta]",
            "system_color": "purple",
            "system_title": "[bold purple]System[/bold purple]",
            "tool_color": "dim cyan",
            "tool_title": "[bold dim cyan]Tool[/bold dim cyan]",
        },
        "colorblind": {
            # Colorblind-friendly palette (blue/yellow/orange)
            # Safe for deuteranopia, protanopia, and tritanopia
            "user_color": "blue",
            "user_title": "[bold blue]You[/bold blue]",
            "assistant_color": "yellow",
            "assistant_title": "[bold yellow]Clio[/bold yellow]",
            "system_color": "bright_yellow",
            "system_title": "[bold bright_yellow]System[/bold bright_yellow]",
            "tool_color": "dim blue",
            "tool_title": "[bold dim blue]Tool[/bold dim blue]",
        }
    }

    CSS = """
    Screen {
        overflow-x: hidden;
        overflow-y: auto;
    }

    #chat-log {
        height: 1fr;
        min-height: 15;
        width: 100%;
        max-width: 100%;
        border: solid $primary;
        padding: 1;
        overflow-x: hidden;
        overflow-y: auto;
        margin-bottom: 0;
    }

    #thinking-indicator {
        height: 1;
        width: 100%;
        padding: 0 2;
        background: $surface;
    }

    #thinking-indicator.hidden {
        display: none;
    }

    #input-container {
        height: auto;
        min-height: 5;
        width: 100%;
        max-width: 100%;
        padding: 0;
        margin-bottom: 0;
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

    #chat-input {
        width: 100%;
        height: auto;
        min-height: 3;
        max-height: 8;
        border: solid $primary;
    }

    #escape-hint {
        width: 100%;
        height: auto;
        padding: 0 1;
        color: $text-muted;
        text-style: dim;
    }

    #escape-hint.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
    ]

    # Enable terminal text selection by not capturing mouse events
    # Users can hold Shift and select text with the mouse
    ENABLE_COMMAND_PALETTE = False
    
    def __init__(self, launch_dir: Optional[str] = None, conversation_id: Optional[int] = None):
        """Initialize app.

        Args:
            launch_dir: Working directory for the app
            conversation_id: If provided, resume from this conversation
        """
        super().__init__()

        # Store the working directory from when the app was launched
        self.launch_dir = launch_dir or os.getcwd()
        self.conversation_id = conversation_id

        # Initialize components
        self.config_manager = ConfigManager()
        self.context_manager = ContextManager(working_dir=self.launch_dir)
        self.agent = Agent(
            self.config_manager,
            self.request_permission,
            self.on_tool_executed,
            conversation_id=conversation_id
        )
        self.command_router = CommandRouter()

        # Register commands
        self._register_commands()

        # IDE bridge will be connected on mount (when event loop is running)
        self._ide_bridge_connected = False

        # State
        self.pending_permission: Optional[asyncio.Future] = None
        self.last_assistant_response: str = ""
        self.conversation_history: List[Dict[str, str]] = []
        self.thinking_indicator: Optional[ThinkingIndicator] = None

        # Command history
        self.command_history: List[str] = []
        self.history_index: int = -1
        self.current_draft: str = ""

        # Escape key tracking for double-tap to clear
        self.escape_pressed_once: bool = False
        self.escape_timer: Optional[asyncio.TimerHandle] = None

        # Tool call batching - collect multiple tool calls into one panel
        self.pending_tool_calls: List[str] = []
        self.tool_batch_timer: Optional[asyncio.TimerHandle] = None

        # Display messages for responsive re-rendering on resize
        self.display_messages: List[tuple] = []  # (content, title, border_style)

        # For handling /history restart
        self.selected_conversation_id: Optional[int] = None

    def _get_colors(self) -> dict:
        """Get color map based on colorblind mode setting."""
        config = self.config_manager.load()
        mode = "colorblind" if config.preferences.colorblind_mode else "normal"
        return self.COLOR_MAPS[mode]

    def compose(self) -> ComposeResult:
        """Compose UI."""
        yield Header()

        # Status bar
        yield Static(self._get_status_text(), id="status-bar")

        # Chat log with low min_width to allow dynamic resizing
        yield RichLog(id="chat-log", wrap=True, markup=True, min_width=10)

        # Thinking indicator (hidden by default)
        yield ThinkingIndicator(id="thinking-indicator", classes="hidden")

        # Input with soft wrapping
        with Container(id="input-container"):
            chat_input = AutocompleteTextArea(
                id="chat-input",
                language=None,  # No syntax highlighting for plain input
                theme="vscode_dark",
                soft_wrap=True,
                show_line_numbers=False,
                tab_behavior="indent"
            )
            yield chat_input
            yield Label("", id="escape-hint", classes="hidden")

        # Custom autocomplete overlay
        yield AutocompleteOverlay(Path(self.launch_dir), id="autocomplete-overlay")

        yield Footer()
    
    def _get_status_text(self) -> str:
        """Get status bar text."""
        config = self.config_manager.load()
        provider = self.agent.current_provider_name
        model = self.agent.current_model

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

        # Get session usage
        session_usage = self.agent.history_db.get_session_usage(self.agent.conversation_id)
        session_tokens = session_usage.get('prompt_tokens', 0) + session_usage.get('completion_tokens', 0)
        session_cost = session_usage.get('total_cost', 0.0)

        return f"🤖 {model} @ {hostname} | 📂 {cwd_short} | 🔢 {session_tokens:,} tokens | 💵 ${session_cost:.4f}"

    async def _do_bridge_connect(self) -> None:
        """Async task to connect to IDE bridge."""
        try:
            bridge = get_bridge()
            connected = await bridge.connect()
            if connected:
                self._ide_bridge_connected = True
                chat_log = self.query_one("#chat-log", RichLog)
                chat_log.write("[dim]✓ Connected to IDE - edits will appear in real-time![/dim]")
        except Exception as e:
            # Silently fail - IDE bridge is optional
            pass

    def _register_commands(self) -> None:
        """Register slash commands."""
        self.command_router.register("/help", self._cmd_help)
        self.command_router.register("/clear", self._cmd_clear)
        self.command_router.register("/exit", self._cmd_exit)
        self.command_router.register("/model", self._cmd_model)
        self.command_router.register("/config", self._cmd_config)
        self.command_router.register("/copy", self._cmd_copy)
        self.command_router.register("/export", self._cmd_export)
        self.command_router.register("/history", self._cmd_history)
        self.command_router.register("/cleanup", self._cmd_cleanup)
        self.command_router.register("/usage", self._cmd_usage)
        # /web handled specially in on_input_submitted - no command handler needed
    
    def _cmd_help(self, args: str) -> str:
        """Show help."""
        return """**Available Commands:**

- `/help` - Show this help message
- `/model` - List and switch models (interactive)
- `/clear` - Clear conversation history
- `/exit` - Exit the application
- `/config` - Show configuration
- `/copy` - Copy last assistant response to clipboard
- `/export [filename]` - Export conversation to markdown file
- `/history` - Resume a previous conversation (interactive selection)
- `/cleanup` - Delete old conversations (keep only 20 most recent)
- `/usage` - Show token usage and cost breakdown for this month
- `/web <query>` - Search the web and get AI response

**Working with Files:**
The AI can read, write, and edit files using built-in tools. Just ask naturally:
- "Read the contents of auth.py"
- "Edit server.js and change the port to 3000"
- "List all Python files in the src directory"
- "Search for the function called handleLogin"

You can also use `@filename` syntax to reference files:
- `@auth.py` - The AI will read this file when needed
- `@"path with spaces.txt"` - Use quotes for paths with spaces

**Text Selection:**
- Hold **Shift** and drag with mouse to select text
- Then use Ctrl+Shift+C (or Cmd+C on Mac) to copy

**Accessibility:**
- Enable colorblind mode in `~/.clio/config.json`:
  - Set `"colorblind_mode": true` under `preferences`
  - Uses blue/yellow/orange palette (safe for all colorblind types)

**Examples:**
- "Add error handling to @auth.py"
- "/model" to switch models
- "/history" to resume a conversation
- "/copy" to copy last response
- "/export my-chat.md" to save conversation
- "/web latest React 19 features" to search the web
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

        # Model pricing info (input/output per 1M tokens)
        model_prices = {
            "gpt-5.2": "(in: $1.25, out: $10 per 1M)",
            "gpt-4.1": "(in: $2, out: $8 per 1M)",
            "gpt-4.1-mini": "(in: $0.50, out: $2 per 1M)",
            "gpt-4.1-nano": "(in: $0.10, out: $0.50 per 1M)",
            "o1": "(in: $15, out: $60 per 1M)",
            "o3-mini": "(in: $1.10, out: $4.40 per 1M)",
            "gpt-4o-mini": "(in: $0.15, out: $0.60 per 1M)",
            "gpt-4o": "(in: $2.50, out: $10 per 1M)",
        }

        # Build list of all available models
        model_options = []
        for provider_name, provider_config in config.providers.items():
            hostname = provider_config.hostname or provider_config.baseURL or provider_name
            for model in provider_config.models:
                is_current = (provider_name == self.agent.current_provider_name and
                            model == self.agent.current_model)
                marker = "●" if is_current else "○"
                # Add pricing if available - use actual spacing for alignment
                price_info = f"  {model_prices[model]}" if model in model_prices else ""
                display_text = f"{marker} {model}{price_info}  @ {hostname}"
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
        """Open config file in editor."""
        import subprocess
        import os

        # Get editor from environment or use fallback
        editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'nano'

        # Get config path
        config_path = str(self.config_manager.config_path)

        try:
            # Suspend Textual, run editor, then resume
            with self.suspend():
                subprocess.run([editor, config_path])

            return f"✓ Config file edited: {config_path}\n\nRestart clio for changes to take effect."
        except Exception as e:
            return f"❌ Failed to open editor: {e}\n\nYou can manually edit: {config_path}"

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

    def _cmd_history(self, args: str) -> str:
        """List recent conversations with interactive selection."""
        # Launch the history selection screen in a worker
        self.run_worker(self._show_history_screen(), exclusive=True)
        return ""  # Return immediately, worker handles the rest

    async def _show_history_screen(self):
        """Worker method to show history selection screen."""
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=20)
        db.close()

        if not conversations:
            colors = self._get_colors()
            self._write_message("No conversation history found.", title=colors["system_title"], border_style=colors["system_color"], align="center")
            return

        # Show modal screen for selection (now running in worker context)
        selected_conv_id = await self.push_screen_wait(HistorySelectScreen(conversations))

        if selected_conv_id:
            # User selected a conversation - set it and exit
            # The CLI will detect this and restart with the selected conversation
            self.selected_conversation_id = selected_conv_id
            self.exit()
        # If cancelled, just return (modal closes)

    def _cmd_cleanup(self, args: str) -> str:
        """Delete old conversations (keep only 20 most recent)."""
        db = HistoryDatabase()
        deleted = db.cleanup_old_conversations(keep_recent=20)
        db.close()

        if deleted:
            return f"✓ Deleted {deleted} old conversation(s)"
        else:
            return "✓ No old conversations to delete"

    def _cmd_usage(self, args: str) -> str:
        """Show usage statistics and costs."""
        from datetime import datetime

        # Get monthly usage
        monthly_usage = self.agent.history_db.get_monthly_usage()

        if not monthly_usage:
            return "No usage data for this month yet."

        # Format table
        month_name = datetime.now().strftime("%B %Y")
        lines = [f"📊 **{month_name} Usage**\n"]
        lines.append("```")

        # Table header with fixed column widths
        lines.append(f"{'Model':<16} {'In Tokens':>10} {'Out Tokens':>12} {'Cost':>8}")
        lines.append("─" * 50)

        # Table rows
        total_in = 0
        total_out = 0
        total_cost = 0.0

        for row in monthly_usage:
            model = row['model']
            in_tokens = row['prompt_tokens']
            out_tokens = row['completion_tokens']
            cost = row['total_cost']

            total_in += in_tokens
            total_out += out_tokens
            total_cost += cost

            # Format tokens (K for thousands)
            in_k = f"{in_tokens / 1000:.1f}K" if in_tokens >= 1000 else str(in_tokens)
            out_k = f"{out_tokens / 1000:.1f}K" if out_tokens >= 1000 else str(out_tokens)

            # Format model name (truncate if needed)
            model_display = model[:16].ljust(16)

            lines.append(f"{model_display} {in_k:>10} {out_k:>12} ${cost:>7.2f}")

        # Total row
        lines.append("")  # Blank line before total
        lines.append("─" * 50)
        total_in_k = f"{total_in / 1000:.1f}K" if total_in >= 1000 else str(total_in)
        total_out_k = f"{total_out / 1000:.1f}K" if total_out >= 1000 else str(total_out)
        lines.append(f"{'Total':<16} {total_in_k:>10} {total_out_k:>12} ${total_cost:>7.2f}")
        lines.append("```")

        return "\n".join(lines)

    def _create_panel(self, content, title="", border_style="blue", align="left"):
        """Create a responsive panel that adapts to terminal width.

        Args:
            content: The content to display
            title: Panel title
            border_style: Border color/style
            align: Text alignment - "left", "center", or "right"
        """
        from rich.text import Text

        # For plain strings, convert to Text with explicit justify to control alignment
        if isinstance(content, str):
            # Use from_markup to parse Rich markup tags like [bold], [cyan], etc.
            text_obj = Text.from_markup(content)
            text_obj.justify = "left" if align == "left" else "center"
            content = text_obj
        # For other renderables (Markdown, Text), wrap with Align
        elif align == "center":
            content = Align.center(content)
        else:
            # Explicitly left-align
            content = Align.left(content)

        return Panel(content, title=title, border_style=border_style, expand=True)

    def _write_message(self, content, title="", border_style="blue", content_type="auto", align="left"):
        """Write a message to chat log and store for re-rendering.

        Args:
            content: Either a string (for raw text/markdown) or a renderable
            content_type: "markdown", "text", or "auto" to detect from type
            align: Text alignment - "left" for user/assistant, "center" for system/tool
        """
        chat_log = self.query_one("#chat-log", RichLog)

        # Determine content type and extract raw string if possible
        raw_content = None
        if isinstance(content, str):
            raw_content = content
            detected_type = "text"
        elif isinstance(content, Markdown):
            raw_content = content.markup  # Extract the markdown string
            detected_type = "markdown"
        else:
            # For other renderables (Text, etc), store the object
            detected_type = "renderable"

        final_type = content_type if content_type != "auto" else detected_type
        self.display_messages.append((raw_content if raw_content else content, title, border_style, final_type, align))
        # Use expand and shrink to allow dynamic resizing
        chat_log.write(self._create_panel(content, title=title, border_style=border_style, align=align), expand=True, shrink=True)

    def on_resize(self, event: events.Resize) -> None:
        """Handle terminal resize by re-rendering all messages."""
        debug_log = "/tmp/clio_resize_debug.log"
        try:
            chat_log = self.query_one("#chat-log", RichLog)

            with open(debug_log, "a") as f:
                f.write(f"\n=== RESIZE EVENT ===\n")
                f.write(f"Terminal size: {event.size}\n")
                f.write(f"chat_log.size: {chat_log.size}\n")
                f.write(f"chat_log.scrollable_content_region: {chat_log.scrollable_content_region}\n")
                f.write(f"chat_log.scrollable_content_region.width: {chat_log.scrollable_content_region.width}\n")

            # Clear the line cache if it exists
            if hasattr(chat_log, '_line_cache'):
                chat_log._line_cache.clear()

            # Reset virtual size tracking
            if hasattr(chat_log, '_widest_line_width'):
                chat_log._widest_line_width = 0

            chat_log.clear()
            chat_log.refresh()

            # Re-write all messages with expand and shrink to adapt to new width
            for stored_content, title, border_style, content_type, align in self.display_messages:
                if content_type == "markdown":
                    content = Markdown(stored_content)
                elif content_type == "text":
                    content = stored_content
                else:
                    content = stored_content  # Use stored renderable as-is

                # Use expand and shrink for dynamic resizing
                chat_log.write(self._create_panel(content, title=title, border_style=border_style, align=align), expand=True, shrink=True)

            with open(debug_log, "a") as f:
                f.write(f"After rewrite - chat_log.scrollable_content_region.width: {chat_log.scrollable_content_region.width}\n")
                f.write(f"After rewrite - chat_log._widest_line_width: {chat_log._widest_line_width}\n")

            chat_log.refresh()
        except Exception as e:
            import traceback
            with open(debug_log, "a") as f:
                f.write(f"ERROR: {e}\n{traceback.format_exc()}\n")

    async def on_mount(self) -> None:
        """Handle mount."""
        chat_log = self.query_one("#chat-log", RichLog)

        # Get session log path
        log_path = self.agent.session_logger.get_log_path()

        # If resuming a conversation, show history
        if self.conversation_id:
            from ..history.database import HistoryDatabase
            db = HistoryDatabase()
            messages = db.get_conversation_messages(self.conversation_id)
            db.close()

            if messages:
                colors = self._get_colors()
                self._write_message(
                    f"[bold cyan]Resuming Conversation #{self.conversation_id}[/bold cyan]\n\n"
                    f"📝 Session log: [dim]{log_path}[/dim]\n\n"
                    f"[dim]Loaded {len(messages)} previous messages[/dim]",
                    title=colors["system_title"].replace("System", "Welcome Back"),
                    border_style=colors["system_color"],
                    align="center"
                )

                # Display conversation history
                for msg in messages:
                    role = msg["role"]
                    content = msg["content"]

                    if role == "user":
                        self._write_message(content, title=colors["user_title"], border_style=colors["user_color"])
                    elif role == "assistant":
                        # Skip empty assistant messages (tool calls with no response)
                        if content and content.strip():
                            self._write_message(Markdown(content), title=colors["assistant_title"], border_style=colors["assistant_color"])
                    elif role == "tool":
                        # Show tool results in dim (truncate long results)
                        if len(content) > 200:
                            chat_log.write(f"[dim]🔧 {content[:200]}...[/dim]")
                        else:
                            chat_log.write(f"[dim]🔧 {content}[/dim]")

                    # Add to conversation history for /export etc
                    self.conversation_history.append({"role": role, "content": content})

                colors = self._get_colors()
                self._write_message(
                    "─── End of previous conversation ───",
                    title=colors["system_title"],
                    border_style=colors["system_color"],
                    align="center"
                )
        else:
            # New conversation
            colors = self._get_colors()
            self._write_message(
                "[bold cyan]CLIO[/bold cyan] - Command Line Interactive Operator\n\n"
                "A self-hosted AI coding assistant.\n\n"
                f"📝 Session log: [dim]{log_path}[/dim]\n\n"
                "Type [bold]/help[/bold] for commands or start chatting!",
                title=colors["system_title"].replace("System", "Welcome"),
                border_style=colors["system_color"],
                align="center"
            )

        # Try to connect to IDE bridge (now that event loop is running)
        asyncio.create_task(self._do_bridge_connect())

        # Focus input
        self.query_one("#chat-input", TextArea).focus()

    async def on_autocomplete_text_area_submit_message(self, message: AutocompleteTextArea.SubmitMessage) -> None:
        """Handle Enter key to submit message."""
        import datetime
        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] SUBMIT MESSAGE HANDLER CALLED!\n")
            f.flush()

        chat_input = self.query_one("#chat-input", AutocompleteTextArea)
        user_input = chat_input.text.strip()

        if not user_input:
            return

        # Add to command history
        if not self.command_history or self.command_history[-1] != user_input:
            self.command_history.append(user_input)

        # Reset history navigation
        self.history_index = -1
        self.current_draft = ""

        # Clear input
        chat_input.clear()

        # Process the message
        await self._process_message(user_input)

    async def on_autocomplete_text_area_autocomplete_key(self, message: AutocompleteTextArea.AutocompleteKey) -> None:
        """Handle Tab/Enter in autocomplete mode."""
        self._debug_log(f"🔍 Got AutocompleteKey message: key={message.key}")

        chat_input = self.query_one("#chat-input", AutocompleteTextArea)
        autocomplete = self.query_one("#autocomplete-overlay", AutocompleteOverlay)

        # Save trigger before hiding (hide() sets it to None)
        trigger = autocomplete.current_trigger
        self._debug_log(f"🔍 Saved trigger before hide: '{trigger}'")

        # Apply completion
        completion = autocomplete.get_selected_completion()
        self._debug_log(f"🔍 Completion selected: {completion}")

        if completion:
            self._apply_completion(chat_input, autocomplete, completion)

            # NOTE: File autocomplete no longer adds to context
            # The @ mention stays in the message for the model to use read_file tool
            # if autocomplete.current_trigger == '@':
            #     file_path = completion
            #     try:
            #         result = await self._cmd_add(file_path)
            #         chat_log = self.query_one("#chat-log", RichLog)
            #         chat_log.write(self._create_panel(result, "System", "purple"))
            #     except Exception as e:
            #         chat_log = self.query_one("#chat-log", RichLog)
            #         chat_log.write(self._create_panel(f"Error adding file: {e}", "System", "red"))

        autocomplete.hide()
        chat_input.autocomplete_visible = False

        # If Enter was pressed on a slash command, submit it immediately
        self._debug_log(f"🔍 Checking auto-submit: key={message.key}, trigger={trigger}")
        if message.key == "enter" and trigger == "/":
            self._debug_log(f"🔍 Enter pressed on slash command, auto-submitting")
            user_input = chat_input.text.strip()
            self._debug_log(f"🔍 user_input for submit: '{user_input}'")
            if user_input:
                chat_input.clear()
                await self._process_message(user_input)
            else:
                self._debug_log(f"🔍 Empty input, not submitting")

    async def on_autocomplete_text_area_escape_key(self, message: AutocompleteTextArea.EscapeKey) -> None:
        """Handle Escape key press."""
        autocomplete = self.query_one("#autocomplete-overlay", AutocompleteOverlay)
        autocomplete_visible = "visible" in autocomplete.classes

        # If autocomplete is visible, just hide it
        if autocomplete_visible:
            autocomplete.hide()
            chat_input = self.query_one("#chat-input", AutocompleteTextArea)
            chat_input.autocomplete_visible = False
            return

        # Handle double-tap to clear
        chat_input = self.query_one("#chat-input", AutocompleteTextArea)
        if self.escape_pressed_once:
            # Second tap - clear input
            chat_input.clear()
            self._reset_escape_state()
        else:
            # First tap - show hint and start timer
            self.escape_pressed_once = True
            hint = self.query_one("#escape-hint", Label)
            hint.update("Press Escape again to clear")
            hint.remove_class("hidden")

            # Set timer to reset after 2 seconds
            if self.escape_timer:
                self.escape_timer.stop()
            self.escape_timer = self.set_timer(2.0, self._reset_escape_state)

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes for autocomplete."""
        text = event.text_area.text
        cursor = event.text_area.cursor_location
        cursor_row, cursor_col = cursor

        # Find if we should show autocomplete
        trigger, trigger_pos, search_term = self._find_autocomplete_trigger(
            text, cursor_col, cursor_row
        )

        autocomplete = self.query_one("#autocomplete-overlay", AutocompleteOverlay)
        chat_input = self.query_one("#chat-input", AutocompleteTextArea)

        if trigger:
            # Get container region for positioning (includes padding)
            container = self.query_one("#input-container")
            container_region = container.region

            # Show suggestions
            autocomplete.show_suggestions(
                trigger, trigger_pos, search_term,
                container_region, cursor_row, cursor_col
            )
            # Tell TextArea autocomplete is visible
            chat_input.autocomplete_visible = True
        else:
            # Hide autocomplete
            autocomplete.hide()
            chat_input.autocomplete_visible = False

    def _find_autocomplete_trigger(self, text: str, cursor_col: int, cursor_row: int) -> tuple:
        """Find if there's a / or @ that should trigger autocomplete."""
        lines = text.split('\n')
        if cursor_row >= len(lines):
            return (None, -1, "")

        current_line = lines[cursor_row]
        before_cursor = current_line[:cursor_col]

        # Check for / at start of line
        if before_cursor.strip().startswith('/'):
            cmd = before_cursor.strip()[1:]
            if ' ' not in cmd:
                return ('/', 0, cmd)

        # Check for @ anywhere
        last_at = before_cursor.rfind('@')
        if last_at != -1:
            after_at = before_cursor[last_at + 1:]
            if ' ' not in after_at:
                return ('@', last_at, after_at)

        return (None, -1, "")

    def _debug_log(self, message: str):
        """Log debug message to file."""
        import datetime
        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] {message}\n")
            f.flush()

    def _reset_escape_state(self):
        """Reset escape key state and hide hint."""
        self.escape_pressed_once = False
        if self.escape_timer:
            self.escape_timer.stop()
            self.escape_timer = None
        try:
            hint = self.query_one("#escape-hint", Label)
            hint.add_class("hidden")
        except:
            pass

    def _apply_completion(self, chat_input: TextArea, autocomplete: AutocompleteOverlay, completion: str):
        """Apply autocomplete completion when Tab/Enter is pressed."""
        text = chat_input.text
        cursor = chat_input.cursor_location
        cursor_row, cursor_col = cursor

        self._debug_log(f"🔍 DEBUG _apply_completion: text='{text}', cursor=({cursor_row},{cursor_col})")

        lines = text.split('\n')
        if cursor_row >= len(lines):
            self._debug_log(f"🔍 DEBUG: cursor_row {cursor_row} >= len(lines) {len(lines)}, returning")
            return

        current_line = lines[cursor_row]
        before_cursor = current_line[:cursor_col]

        self._debug_log(f"🔍 DEBUG: current_line='{current_line}', before_cursor='{before_cursor}'")

        # Replace based on trigger type
        if autocomplete.current_trigger == '/':
            # Replace from / to cursor with /completion
            new_line = f"/{completion} " + current_line[cursor_col:]
            self._debug_log(f"🔍 DEBUG: Command completion - new_line='{new_line}'")
            lines[cursor_row] = new_line
            chat_input.text = '\n'.join(lines)
            # Move cursor after completion
            chat_input.move_cursor((cursor_row, len(f"/{completion} ")))

        elif autocomplete.current_trigger == '@':
            # Replace from @ to cursor with @completion + space
            last_at = before_cursor.rfind('@')
            self._debug_log(f"🔍 DEBUG: File completion - last_at={last_at}")
            if last_at != -1:
                new_line = current_line[:last_at] + f"@{completion} " + current_line[cursor_col:]
                self._debug_log(f"🔍 DEBUG: File completion - new_line='{new_line}'")
                lines[cursor_row] = new_line
                chat_input.text = '\n'.join(lines)
                # Move cursor after completion and space
                chat_input.move_cursor((cursor_row, last_at + 1 + len(completion) + 1))
            else:
                self._debug_log(f"🔍 DEBUG: Could not find @ in before_cursor!")

    async def on_key(self, event: events.Key) -> None:
        """Handle key presses for submission, history, and autocomplete."""
        # Log EVERY key press first
        self._debug_log(f"🔍 on_key called: key={event.key}")

        chat_input = self.query_one("#chat-input", TextArea)
        autocomplete = self.query_one("#autocomplete-overlay", AutocompleteOverlay)

        # Only handle when input is focused
        if not chat_input.has_focus:
            self._debug_log(f"🔍 Input not focused, ignoring")
            return

        # Check if autocomplete is visible
        autocomplete_visible = "visible" in autocomplete.classes

        self._debug_log(f"🔍 DEBUG on_key: key={event.key}, autocomplete_visible={autocomplete_visible}")

        # Reset escape state on any non-escape key press
        if event.key != "escape" and self.escape_pressed_once:
            self._reset_escape_state()

        # Handle autocomplete navigation
        if autocomplete_visible:
            if event.key == "down":
                self._debug_log(f"🔍 DEBUG: Down arrow in autocomplete")
                autocomplete.navigate_down()
                event.prevent_default()
                return
            elif event.key == "up":
                self._debug_log(f"🔍 DEBUG: Up arrow in autocomplete")
                autocomplete.navigate_up()
                event.prevent_default()
                return
            elif event.key == "tab" or event.key == "enter":
                self._debug_log(f"🔍 DEBUG: INSIDE tab/enter handler!!!")
                # Apply completion and hide autocomplete
                completion = autocomplete.get_selected_completion()
                self._debug_log(f"🔍 DEBUG: Tab/Enter pressed, completion={completion}, trigger={autocomplete.current_trigger}")
                if completion:
                    self._debug_log(f"🔍 DEBUG: Applying completion '{completion}'")
                    self._apply_completion(chat_input, autocomplete, completion)
                else:
                    self._debug_log(f"🔍 DEBUG: No completion selected!")
                autocomplete.hide()

                # If Enter was pressed on a slash command completion, submit it
                if event.key == "enter" and autocomplete.current_trigger == "/":
                    user_input = chat_input.text.strip()
                    if user_input:
                        chat_input.clear()
                        await self._process_message(user_input)

                event.prevent_default()
                event.stop()
                return
        # Submit on Enter (Shift+Enter handled by backslash above)
        if event.key == "enter":
            self._debug_log(f"🔍 ENTER KEY PRESSED (not in autocomplete)")
            user_input = chat_input.text.strip()
            self._debug_log(f"🔍 user_input = '{user_input}'")

            if not user_input:
                self._debug_log(f"🔍 Empty input, returning")
                return

            # Add to command history
            if not self.command_history or self.command_history[-1] != user_input:
                self.command_history.append(user_input)

            # Reset history navigation
            self.history_index = -1
            self.current_draft = ""

            # Clear input
            chat_input.clear()

            self._debug_log(f"🔍 About to call _process_message with: '{user_input}'")
            # Process the message
            await self._process_message(user_input)
            self._debug_log(f"🔍 _process_message completed")
            event.prevent_default()
            event.stop()
            return

        # History navigation - only when at first/last line
        if event.key == "up":
            # Only navigate if cursor is on first line
            if chat_input.cursor_location[0] == 0:
                if self.command_history:
                    if self.history_index == -1:
                        self.current_draft = chat_input.text
                        self.history_index = len(self.command_history) - 1
                    elif self.history_index > 0:
                        self.history_index -= 1

                    chat_input.text = self.command_history[self.history_index]
                    event.prevent_default()

        elif event.key == "down":
            # Only navigate if cursor is on last line
            if chat_input.cursor_location[0] == chat_input.document.line_count - 1:
                if self.command_history and self.history_index != -1:
                    if self.history_index < len(self.command_history) - 1:
                        self.history_index += 1
                        chat_input.text = self.command_history[self.history_index]
                    else:
                        self.history_index = -1
                        chat_input.text = getattr(self, 'current_draft', '')

                    event.prevent_default()

    async def _process_message(self, user_input: str) -> None:
        """Process and send a user message."""
        import asyncio
        self._debug_log(f"🔍 _process_message called with: '{user_input}'")

        colors = self._get_colors()

        # Show user message
        self._write_message(user_input, title=colors["user_title"], border_style=colors["user_color"])

        # Yield to event loop to let UI update before starting AI processing
        await asyncio.sleep(0)

        # Parse command or message
        command, args, original = self.command_router.parse(user_input)
        self._debug_log(f"🔍 Parsed: command='{command}', args='{args}', original='{original}'")

        # Special handling for /web - convert to normal message flow
        actual_message = user_input
        if command == "/web":
            # Convert /web to a normal message that instructs the AI
            actual_message = f"Please search the web for: {args}\n\nUse the web_search tool to find relevant information, then use web_fetch to read the content from official/authoritative sources (prioritize Tier 1 sources), and provide a comprehensive answer with citations."
            command = None  # Treat as normal message

        # Add to conversation history (use actual message for AI)
        self.conversation_history.append({"role": "user", "content": actual_message})

        if command:
            self._debug_log(f"🔍 Executing command: {command} with args: {args}")
            # Execute command
            result = await self.command_router.execute(command, args)
            self._debug_log(f"🔍 Command result: {result[:100]}...")
            self._write_message(Markdown(result), title=colors["system_title"], border_style=colors["system_color"], align="center")

            # Add system message to history
            self.conversation_history.append({"role": "system", "content": result})
        else:
            # NOTE: @ mentions are kept in the message for the model to see
            # The model should use read_file tool when it encounters @filename
            # We no longer pre-load file contents into context

            # Extract @mentions for validation (optional - could remove this entirely)
            # mentions = self.command_router.extract_mentions(user_input)
            # for mention in mentions:
            #     # Could add file existence check here if desired
            #     pass

            # No context injection - empty string
            context = ""

            # Show thinking indicator
            thinking_indicator = self.query_one("#thinking-indicator", ThinkingIndicator)
            thinking_indicator.reset_tokens()
            thinking_indicator.remove_class("hidden")

            try:
                # Use actual_message (transformed for /web or original for normal messages)
                response = await self.agent.chat(actual_message, context)

                # Get latest usage stats for this session to show in thinking indicator
                session_usage = self.agent.history_db.get_session_usage(self.agent.conversation_id)
                if session_usage:
                    thinking_indicator.set_tokens(
                        session_usage.get('prompt_tokens', 0),
                        session_usage.get('completion_tokens', 0)
                    )

                # Brief delay to show final token count before hiding
                await asyncio.sleep(0.5)

                # Hide thinking indicator
                thinking_indicator.add_class("hidden")

                # Flush any pending tool calls BEFORE showing the response
                if self.tool_batch_timer:
                    self.tool_batch_timer.stop()
                    self.tool_batch_timer = None
                self._flush_tool_calls()

                self._write_message(Markdown(response), title=colors["assistant_title"], border_style=colors["assistant_color"])

                # Save last response and add to history
                self.last_assistant_response = response
                self.conversation_history.append({"role": "assistant", "content": response})
            except Exception as e:
                # Hide thinking indicator
                thinking_indicator.add_class("hidden")

                # Get full traceback
                tb = traceback.format_exc()
                error_msg = f"**Error:**\n```\n{str(e)}\n\n{tb}\n```"
                # Keep error as red - universal danger color
                self._write_message(Markdown(error_msg), title="[bold red]Error[/bold red]", border_style="red", align="center")

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
        # For now, batch with tool calls
        # Don't show permission requests - they're redundant with tool execution messages
        return True

    async def on_tool_executed(self, tool_name: str, arguments: dict, result: str) -> None:
        """Handle tool execution notification - batches consecutive tool calls."""
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

        # Add to pending tool calls
        self.pending_tool_calls.append(tool_display)

        # Cancel existing timer if any
        if self.tool_batch_timer:
            self.tool_batch_timer.stop()

        # Set timer to flush after 100ms of no new tool calls
        self.tool_batch_timer = self.set_timer(0.1, self._flush_tool_calls)

    def _flush_tool_calls(self) -> None:
        """Display all batched tool calls in one panel."""
        if not self.pending_tool_calls:
            return

        colors = self._get_colors()

        # Combine all tool calls with newlines
        combined = "\n".join(self.pending_tool_calls)

        # Display in one panel using system colors (purple)
        from rich.markdown import Markdown
        self._write_message(
            Markdown(combined),
            title=colors["system_title"].replace("System", "Tools"),
            border_style=colors["system_color"],
            align="center"
        )

        # Clear the pending list
        self.pending_tool_calls.clear()
        self.tool_batch_timer = None

    def action_clear(self) -> None:
        """Clear chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        self.display_messages.clear()  # Also clear stored messages
        self.agent.clear_history()
        self.conversation_history.clear()
        self.last_assistant_response = ""
