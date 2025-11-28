"""Custom @ file autocomplete widget."""
from pathlib import Path
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem
from textual_autocomplete._autocomplete import TargetState


class FileAutoComplete(AutoComplete):
    """AutoComplete that only triggers on @ character."""

    def __init__(self, target, working_dir: Path, **kwargs):
        self.working_dir = working_dir
        super().__init__(target, candidates=None, **kwargs)

    def _find_at_position(self, state: TargetState) -> int:
        """Find the position of @ before cursor, or -1 if not found."""
        text = state.text
        cursor = state.cursor_position
        before_cursor = text[:cursor]
        last_at = before_cursor.rfind('@')

        # Check if there's a space after the @
        if last_at != -1:
            after_at = before_cursor[last_at + 1:]
            if ' ' in after_at:
                return -1

        return last_at

    def get_search_string(self, state: TargetState) -> str:
        """Override to only search when @ is present."""
        last_at = self._find_at_position(state)

        if last_at == -1:
            # No @ found or space after @, don't show autocomplete
            return ""

        # Get text after @ up to cursor
        text = state.text
        cursor = state.cursor_position
        after_at = text[last_at + 1:cursor]

        return after_at

    def should_show_dropdown(self, search_string: str) -> bool:
        """Override to show dropdown when @ is typed, even with empty search."""
        # Check if there's an @ in the current input
        target_state = self._get_target_state()
        last_at = self._find_at_position(target_state)

        # If no @ found, don't show dropdown
        if last_at == -1:
            return False

        # If @ is present, show dropdown if we have candidates
        option_count = self.option_list.option_count
        if option_count == 0:
            return False

        # Show dropdown for @ even with empty search string
        return True

    def get_candidates(self, state: TargetState) -> list[DropdownItem]:
        """Get file candidates for autocomplete."""
        # Check if @ is present
        last_at = self._find_at_position(state)
        if last_at == -1:
            return []

        # Get the search string (text after @)
        search_string = self.get_search_string(state)

        try:
            items = []
            for item in sorted(self.working_dir.iterdir()):
                name = item.name

                # Skip hidden files
                if name.startswith('.'):
                    continue

                # Filter by search string (case-insensitive)
                if search_string and not name.lower().startswith(search_string.lower()):
                    continue

                # Create dropdown item
                if item.is_dir():
                    items.append(DropdownItem(main=f"{name}/", prefix="📁"))
                else:
                    items.append(DropdownItem(main=name, prefix="📄"))

            return items[:15]  # Limit to 15
        except Exception:
            return []

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Apply completion by replacing text after @ with selected value."""
        target = self.target
        text = state.text
        cursor = state.cursor_position

        # Find the @ position
        last_at = self._find_at_position(state)
        if last_at == -1:
            return

        # Replace everything from @ to cursor with @value
        new_value = text[:last_at] + "@" + value + text[cursor:]
        new_cursor_position = last_at + 1 + len(value)

        with self.prevent(Input.Changed):
            target.value = new_value
            target.cursor_position = new_cursor_position
