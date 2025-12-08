"""Custom / command autocomplete widget."""
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem
from textual_autocomplete._autocomplete import TargetState


class CommandAutoComplete(AutoComplete):
    """AutoComplete that only triggers on / character at start of input."""

    def __init__(self, target, command_router, **kwargs):
        self.command_router = command_router
        super().__init__(target, candidates=None, **kwargs)

    def _get_all_commands(self) -> list[tuple[str, str]]:
        """Get all available commands with descriptions."""
        commands = [
            ("/help", "Show help message"),
            ("/model", "List and switch models"),
            ("/clear", "Clear conversation history"),
            ("/exit", "Exit the application"),
            ("/files", "List files in context"),
            ("/add", "Add file or folder to context"),
            ("/remove", "Remove file from context"),
            ("/config", "Show configuration"),
            ("/copy", "Copy last assistant response"),
            ("/export", "Export conversation to markdown"),
            ("/history", "List recent conversations"),
            ("/continue", "Continue a previous conversation"),
            ("/cleanup", "Delete old conversations"),
            ("/web", "Search the web"),
        ]
        return commands

    def _find_slash_position(self, state: TargetState) -> int:
        """Find if input starts with /, or -1 if not."""
        text = state.text
        cursor = state.cursor_position
        before_cursor = text[:cursor]

        # Only trigger if input starts with / and no space after it
        if before_cursor.startswith('/'):
            if ' ' in before_cursor:
                return -1
            return 0

        return -1

    def get_search_string(self, state: TargetState) -> str:
        """Override to only search when / is at start."""
        slash_pos = self._find_slash_position(state)

        if slash_pos == -1:
            return ""

        # Get text after / up to cursor
        text = state.text
        cursor = state.cursor_position
        after_slash = text[1:cursor]

        return after_slash

    def get_matches(self, target_state, candidates, search_string):
        """Return candidates as-is (already filtered in get_candidates)."""
        return candidates

    def should_show_dropdown(self, search_string: str) -> bool:
        """Show dropdown when / is typed at start."""
        target_state = self._get_target_state()
        slash_pos = self._find_slash_position(target_state)

        # If no / at start, don't show dropdown
        if slash_pos == -1:
            return False

        return True

    def get_candidates(self, state: TargetState) -> list[DropdownItem]:
        """Get command candidates based on search."""
        slash_pos = self._find_slash_position(state)

        if slash_pos == -1:
            return []

        text = state.text
        cursor = state.cursor_position
        search_term = text[1:cursor].lower()

        all_commands = self._get_all_commands()

        # If no search term, show all commands
        if not search_term:
            return [
                DropdownItem(main=f"{cmd} - {desc}", prefix="⚡")
                for cmd, desc in all_commands
            ]

        # Filter commands by search term
        matched = []
        for cmd, desc in all_commands:
            cmd_name = cmd[1:]  # Remove leading /
            if cmd_name.startswith(search_term):
                matched.append((0, DropdownItem(main=f"{cmd} - {desc}", prefix="⚡")))
            elif search_term in cmd_name:
                matched.append((1, DropdownItem(main=f"{cmd} - {desc}", prefix="⚡")))

        matched.sort(key=lambda x: x[0])
        return [item[1] for item in matched]

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Apply completion - replace from / to cursor with selected command."""
        target = self.target
        text = state.text
        cursor = state.cursor_position

        # Find the / position
        slash_pos = self._find_slash_position(state)
        if slash_pos == -1:
            return

        # Extract just the command name (before " - ")
        if " - " in value:
            command = value.split(" - ")[0]
        else:
            command = value

        # Replace from / to cursor with the selected command
        new_value = command + " " + text[cursor:]
        new_cursor_position = len(command) + 1

        with self.prevent(Input.Changed):
            target.value = new_value
            target.cursor_position = new_cursor_position

        self.action_hide()
