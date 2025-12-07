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

        # For filtering, return only the part after the last /
        if '/' in after_at:
            return after_at[after_at.rfind('/') + 1:]

        return after_at

    def should_show_dropdown(self, search_string: str) -> bool:
        """Override to show dropdown when @ is typed, even with empty search."""
        # Check if there's an @ in the current input
        target_state = self._get_target_state()
        last_at = self._find_at_position(target_state)

        with open("/tmp/clio_debug.log", "a") as f:
            f.write(f"should_show: search='{search_string}', @pos={last_at}, opts={self.option_list.option_count}\n")

        # If no @ found, don't show dropdown
        if last_at == -1:
            return False

        # If @ is present, always return True
        # The option list will be rebuilt with candidates by the caller
        # We can't rely on option_count here because it may not be updated yet
        return True

    def get_candidates(self, state: TargetState) -> list[DropdownItem]:
        """Get file candidates for autocomplete, supporting nested directories."""
        # Check if @ is present
        last_at = self._find_at_position(state)
        if last_at == -1:
            return []

        # Get the FULL path after @ directly from state (not from get_search_string)
        # get_search_string only returns the part after last / for filtering
        text = state.text
        cursor = state.cursor_position
        full_path = text[last_at + 1:cursor]

        try:
            # Determine which directory to list and what to filter by
            if '/' in full_path:
                # User is navigating into a directory
                # Split into directory path and search term
                last_slash = full_path.rfind('/')
                dir_path = full_path[:last_slash]
                search_term = full_path[last_slash + 1:]

                # Resolve the directory relative to working_dir
                current_dir = self.working_dir / dir_path
            else:
                # No slash yet, listing from working_dir
                current_dir = self.working_dir
                search_term = full_path

            with open("/tmp/clio_debug.log", "a") as f:
                f.write(f"get_cand: path='{full_path}', dir={current_dir}, term='{search_term}'\n")

            # Check if directory exists
            if not current_dir.exists() or not current_dir.is_dir():
                with open("/tmp/clio_debug.log", "a") as f:
                    f.write(f"  DIR MISSING\n")
                return []

            items = []
            for item in sorted(current_dir.iterdir()):
                name = item.name

                # Skip hidden files
                if name.startswith('.'):
                    continue

                # Filter by search term (case-insensitive)
                if search_term and not name.lower().startswith(search_term.lower()):
                    continue

                # Create dropdown item
                if item.is_dir():
                    items.append(DropdownItem(main=f"{name}/", prefix="📁"))
                else:
                    items.append(DropdownItem(main=name, prefix="📄"))

            with open("/tmp/clio_debug.log", "a") as f:
                f.write(f"  FOUND {len(items)}\n")
            return items[:15]  # Limit to 15
        except Exception as e:
            with open("/tmp/clio_debug.log", "a") as f:
                f.write(f"  ERROR: {e}\n")
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

        # Get the full path after @, and preserve directory path
        full_path_after_at = text[last_at + 1:cursor]

        # If we're in a nested directory, preserve the directory path
        if '/' in full_path_after_at:
            # Extract the directory path (everything before the last /)
            last_slash = full_path_after_at.rfind('/')
            dir_path = full_path_after_at[:last_slash + 1]
            # Combine directory path with the selected value
            complete_path = dir_path + value
        else:
            # No directory path, just use the value
            complete_path = value

        # Replace everything from @ to cursor with @complete_path
        new_value = text[:last_at] + "@" + complete_path + text[cursor:]
        new_cursor_position = last_at + 1 + len(complete_path)

        with self.prevent(Input.Changed):
            target.value = new_value
            target.cursor_position = new_cursor_position

        # CRITICAL: Rebuild options after completion (like base class does)
        # This updates the dropdown to show contents of the new directory
        new_target_state = self._get_target_state()
        self._rebuild_options(
            new_target_state, self.get_search_string(new_target_state)
        )

    def post_completion(self) -> None:
        """Keep dropdown open if completed value is a directory (ends with /)."""
        # If the completed path doesn't end with /, it's a file - hide dropdown
        if not self.target.value.endswith("/"):
            self.action_hide()
