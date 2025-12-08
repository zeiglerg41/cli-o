"""Custom autocomplete overlay for TextArea widget."""
from pathlib import Path
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from textual.containers import Container
from textual.app import ComposeResult
from rich.text import Text


class AutocompleteOverlay(Container):
    """Autocomplete dropdown overlay for TextArea."""

    DEFAULT_CSS = """
    AutocompleteOverlay {
        display: none;
        width: 100%;
        height: auto;
        max-height: 10;
        background: $surface;
        border: solid $primary;
    }

    AutocompleteOverlay.visible {
        display: block;
    }

    AutocompleteOverlay OptionList {
        width: 100%;
        height: auto;
        max-height: 10;
        background: $surface;
        border: none;
    }
    """

    def __init__(self, working_dir: Path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.working_dir = working_dir
        self.commands = ['help', 'model', 'clear', 'exit', 'files', 'add',
                        'remove', 'config', 'copy', 'export', 'history',
                        'cleanup', 'continue', 'web']
        self.current_trigger = None  # '/' or '@' or None
        self.trigger_pos = -1
        self.search_term = ""

    def compose(self) -> ComposeResult:
        """Compose the overlay."""
        yield OptionList(id="autocomplete-options")

    def show_suggestions(self, trigger: str, trigger_pos: int, search_term: str,
                        textarea_region, cursor_row: int, cursor_col: int):
        """Show autocomplete suggestions."""
        self.current_trigger = trigger
        self.trigger_pos = trigger_pos
        self.search_term = search_term

        # Get matches
        if trigger == '/':
            matches = self._get_command_matches(search_term)
            items = [self._format_command_option(cmd) for cmd in matches]
        elif trigger == '@':
            matches = self._get_file_matches(search_term)
            items = [self._format_file_option(m) for m in matches]
        else:
            self.hide()
            return

        if not items:
            self.hide()
            return

        # Update option list
        option_list = self.query_one("#autocomplete-options", OptionList)
        option_list.clear_options()
        for item in items:
            option_list.add_option(item)

        # Highlight the first option by default
        if len(items) > 0:
            option_list.highlighted = 0

        # Show overlay
        self.remove_class("hidden")
        self.add_class("visible")

        # Use offset to scoot it up closer to the input
        self.styles.offset = (0, -2)

    def hide(self):
        """Hide the overlay."""
        self.remove_class("visible")
        self.add_class("hidden")
        self.current_trigger = None

    def get_selected_completion(self) -> str | None:
        """Get the currently selected completion text."""
        option_list = self.query_one("#autocomplete-options", OptionList)

        # Debug: Log state to file
        import datetime
        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] DEBUG get_selected_completion: highlighted={option_list.highlighted}, option_count={option_list.option_count}\n")
            f.flush()

        if option_list.highlighted is None:
            with open("/tmp/clio_autocomplete_debug.log", "a") as f:
                timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                f.write(f"[{timestamp}] DEBUG: highlighted is None, returning None\n")
                f.flush()
            return None

        # Get the option data
        option = option_list.get_option_at_index(option_list.highlighted)
        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] DEBUG: option={option}, has id={hasattr(option, 'id') if option else False}, id={option.id if option and hasattr(option, 'id') else 'N/A'}\n")
            f.flush()

        if option and hasattr(option, 'id') and option.id:
            with open("/tmp/clio_autocomplete_debug.log", "a") as f:
                timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                f.write(f"[{timestamp}] DEBUG: Returning completion: '{option.id}'\n")
                f.flush()
            return option.id

        with open("/tmp/clio_autocomplete_debug.log", "a") as f:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] DEBUG: No valid option, returning None\n")
            f.flush()
        return None

    def navigate_up(self):
        """Move selection up."""
        option_list = self.query_one("#autocomplete-options", OptionList)
        option_list.action_cursor_up()

    def navigate_down(self):
        """Move selection down."""
        option_list = self.query_one("#autocomplete-options", OptionList)
        option_list.action_cursor_down()

    def _get_command_matches(self, search_term: str) -> list:
        """Get matching commands."""
        if not search_term:
            return self.commands

        search_lower = search_term.lower()
        prefix = [cmd for cmd in self.commands if cmd.startswith(search_lower)]
        contains = [cmd for cmd in self.commands if search_lower in cmd and cmd not in prefix]

        return prefix + contains

    def _get_file_matches(self, search_term: str, max_results: int = 15) -> list:
        """Get matching files/dirs. Returns list of (type, display, full_path)."""
        results = []

        # Directory navigation mode (has /)
        if '/' in search_term:
            last_slash = search_term.rfind('/')
            dir_path = search_term[:last_slash]
            partial = search_term[last_slash + 1:]

            current_dir = self.working_dir / dir_path
            if not current_dir.exists() or not current_dir.is_dir():
                return []

            for item in sorted(current_dir.iterdir()):
                if item.name.startswith('.'):
                    continue
                if partial and not item.name.lower().startswith(partial.lower()):
                    continue

                if item.is_dir():
                    results.append(('dir', item.name + '/', str(item.relative_to(self.working_dir)) + '/'))
                else:
                    results.append(('file', item.name, str(item.relative_to(self.working_dir))))

                if len(results) >= max_results:
                    break

            return results

        # Fuzzy search mode
        else:
            # Empty - show current dir
            if not search_term:
                for item in sorted(self.working_dir.iterdir()):
                    if item.name.startswith('.'):
                        continue

                    if item.is_dir():
                        results.append(('dir', item.name + '/', item.name + '/'))
                    else:
                        results.append(('file', item.name, item.name))

                    if len(results) >= max_results:
                        break

                return results

            # Fuzzy search
            search_lower = search_term.lower()
            matched = []

            for file_path in self.working_dir.rglob('*'):
                if any(part.startswith('.') for part in file_path.parts):
                    continue
                if any(part in ['node_modules', '__pycache__', 'venv', '.git']
                       for part in file_path.parts):
                    continue

                if not file_path.is_file():
                    continue

                try:
                    rel_path = str(file_path.relative_to(self.working_dir))
                    filename = file_path.name

                    if search_lower in filename.lower():
                        matched.append((0, ('file', filename, rel_path)))
                    elif search_lower in rel_path.lower():
                        matched.append((1, ('file', filename, rel_path)))

                    if len(matched) >= 100:
                        break

                except ValueError:
                    continue

            matched.sort(key=lambda x: (x[0], x[1][2]))
            return [item[1] for item in matched[:max_results]]

    def _format_command_option(self, cmd: str) -> Option:
        """Format a command as an Option."""
        display = Text()
        display.append("⚡ ", style="bold cyan")
        display.append(f"/{cmd}", style="cyan")
        return Option(display, id=cmd)

    def _format_file_option(self, file_data: tuple) -> Option:
        """Format a file/dir as an Option."""
        type_marker, display_name, full_path = file_data
        display = Text()

        if type_marker == 'dir':
            display.append("📁 ", style="bold blue")
            display.append(full_path, style="blue")  # Show full path instead of just name
        else:
            display.append("📄 ", style="dim")
            display.append(full_path, style="white")  # Show full path instead of just name

        return Option(display, id=full_path)
