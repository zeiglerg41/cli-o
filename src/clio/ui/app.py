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
from textual.widgets import Header, Footer, Input, TextArea, RichLog, Static, OptionList
from textual.widgets.option_list import Option
from textual.binding import Binding
from textual import events
from textual.message import Message
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.console import Console

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
    
    def compose(self) -> ComposeResult:
        """Compose UI."""
        yield Header()

        # Status bar
        yield Static(self._get_status_text(), id="status-bar")

        # Chat log
        yield RichLog(id="chat-log", wrap=True, markup=True)

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

        # Custom autocomplete overlay
        yield AutocompleteOverlay(Path(self.launch_dir), id="autocomplete-overlay")

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
        self.command_router.register("/files", self._cmd_files)
        self.command_router.register("/add", self._cmd_add)
        self.command_router.register("/remove", self._cmd_remove)
        self.command_router.register("/config", self._cmd_config)
        self.command_router.register("/copy", self._cmd_copy)
        self.command_router.register("/export", self._cmd_export)
        self.command_router.register("/history", self._cmd_history)
        self.command_router.register("/cleanup", self._cmd_cleanup)
        self.command_router.register("/continue", self._cmd_continue)
        # /web handled specially in on_input_submitted - no command handler needed
    
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
- `/history` - List recent conversations
- `/continue <id>` - Continue a previous conversation (exits current session)
- `/cleanup` - Delete old conversations (keep only 20 most recent)
- `/web <query>` - Search the web and get AI response

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
- `/history` to list recent conversations
- `/continue 5` to resume conversation #5
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

    def _cmd_history(self, args: str) -> str:
        """List recent conversations."""
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=20)
        db.close()

        if not conversations:
            return "No conversation history found."

        lines = ["**📜 Recent Conversations (20 most recent):**\n"]

        for conv in conversations:
            conv_id = conv['id']
            start_time = datetime.fromisoformat(conv['start_time']).strftime('%Y-%m-%d %H:%M:%S')
            model = conv['model']
            msg_count = conv['message_count']
            title = conv['title'] or f"Conversation in {Path(conv['working_dir']).name}"
            starred = "⭐ " if conv['starred'] else ""

            lines.append(f"\n**[{conv_id}]** {starred}{title}")
            lines.append(f"  {start_time} | {model} | {msg_count} messages")

        lines.append("\n\n💡 Type `/continue <id>` to resume a conversation")

        return "\n".join(lines)

    def _cmd_cleanup(self, args: str) -> str:
        """Delete old conversations (keep only 20 most recent)."""
        db = HistoryDatabase()
        deleted = db.cleanup_old_conversations(keep_recent=20)
        db.close()

        if deleted:
            return f"✓ Deleted {deleted} old conversation(s)"
        else:
            return "✓ No old conversations to delete"

    def _cmd_continue(self, args: str) -> str:
        """Continue a previous conversation."""
        if not args.strip():
            return "❌ Usage: /continue <id>\n\nUse `/history` to see available conversations"

        try:
            conversation_id = int(args.strip())
        except ValueError:
            return "❌ Invalid conversation ID. Must be a number."

        # Verify conversation exists
        db = HistoryDatabase()
        conversations = db.get_recent_conversations(limit=100)
        conv_ids = [c['id'] for c in conversations]
        db.close()

        if conversation_id not in conv_ids:
            return f"❌ Conversation {conversation_id} not found.\n\nUse `/history` to see available conversations"

        # Exit and restart with this conversation
        return f"⚠️ To continue conversation {conversation_id}, please exit this session and run:\n\n  `clio --continue {conversation_id}`"

    # _cmd_web removed - /web now flows through normal message path for proper tool display

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

        # If resuming a conversation, show history
        if self.conversation_id:
            from ..history.database import HistoryDatabase
            db = HistoryDatabase()
            messages = db.get_conversation_messages(self.conversation_id)
            db.close()

            if messages:
                chat_log.write(self._create_panel(
                    f"[bold cyan]Resuming Conversation #{self.conversation_id}[/bold cyan]\n\n"
                    f"📝 Session log: [dim]{log_path}[/dim]\n\n"
                    f"[dim]Loaded {len(messages)} previous messages[/dim]",
                    title="Welcome Back"
                ))

                # Display conversation history
                for msg in messages:
                    role = msg["role"]
                    content = msg["content"]

                    if role == "user":
                        chat_log.write(self._create_panel(content, title="[bold cyan]You[/bold cyan]", border_style="cyan"))
                    elif role == "assistant":
                        # Skip empty assistant messages (tool calls with no response)
                        if content and content.strip():
                            chat_log.write(self._create_panel(Markdown(content), title="[bold magenta]Assistant[/bold magenta]", border_style="magenta"))
                    elif role == "tool":
                        # Show tool results in dim (truncate long results)
                        if len(content) > 200:
                            chat_log.write(f"[dim]🔧 {content[:200]}...[/dim]")
                        else:
                            chat_log.write(f"[dim]🔧 {content}[/dim]")

                    # Add to conversation history for /export etc
                    self.conversation_history.append({"role": role, "content": content})

                chat_log.write("[dim]─── End of previous conversation ───[/dim]\n")
        else:
            # New conversation
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
                event.prevent_default()
                event.stop()
                return
            elif event.key == "escape":
                self._debug_log(f"🔍 DEBUG: Escape in autocomplete")
                # Escape cancels autocomplete
                autocomplete.hide()
                event.prevent_default()
                return

        # Submit on Enter (Shift+Enter for newline)
        if event.key == "enter" and not event.shift:
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

        # Show user message
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(self._create_panel(user_input, title="[bold cyan]You[/bold cyan]", border_style="cyan"))

        # Parse command or message
        command, args, original = self.command_router.parse(user_input)

        # Special handling for /web - convert to normal message flow
        actual_message = user_input
        if command == "/web":
            # Convert /web to a normal message that instructs the AI
            actual_message = f"Please search the web for: {args}\n\nUse the web_search tool to find relevant information, then use web_fetch to read the content from official/authoritative sources (prioritize Tier 1 sources), and provide a comprehensive answer with citations."
            command = None  # Treat as normal message

        # Add to conversation history (use actual message for AI)
        self.conversation_history.append({"role": "user", "content": actual_message})

        if command:
            # Execute command
            result = await self.command_router.execute(command, args)
            chat_log.write(self._create_panel(Markdown(result), title="[bold purple]System[/bold purple]", border_style="purple"))

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
            thinking_indicator.remove_class("hidden")

            try:
                # Use actual_message (transformed for /web or original for normal messages)
                response = await self.agent.chat(actual_message, context)

                # Hide thinking indicator
                thinking_indicator.add_class("hidden")

                chat_log.write(self._create_panel(Markdown(response), title="[bold magenta]Assistant[/bold magenta]", border_style="magenta"))

                # Save last response and add to history
                self.last_assistant_response = response
                self.conversation_history.append({"role": "assistant", "content": response})
            except Exception as e:
                # Hide thinking indicator
                thinking_indicator.add_class("hidden")

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
        chat_log.write(f"[dim]⚠️  {operation}: {details}[/dim]")

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
            title="[bold blue]Tool Execution[/bold blue]",
            border_style="blue"
        ))
    
    def action_clear(self) -> None:
        """Clear chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        self.agent.clear_history()
        self.conversation_history.clear()
        self.last_assistant_response = ""
