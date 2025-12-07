"""Custom @ file autocomplete widget."""
from pathlib import Path
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem
from textual_autocomplete._autocomplete import TargetState


class FileAutoComplete(AutoComplete):
    """AutoComplete that only triggers on @ character."""

    def __init__(self, target, working_dir: Path, **kwargs):
        self.working_dir = working_dir
        self._file_cache = None  # Cache for file list
        super().__init__(target, candidates=None, **kwargs)

    def _get_all_files(self) -> list[tuple[str, str]]:
        """Get cached list of all files in workspace."""
        if self._file_cache is not None:
            return self._file_cache

        files = []
        # Limit search depth and file count to prevent lag
        count = 0
        max_files = 500

        for file_path in self.working_dir.rglob('*'):
            if count >= max_files:
                break

            # Skip hidden files and common ignore patterns
            if any(part.startswith('.') for part in file_path.parts):
                continue
            if any(part in ['node_modules', '__pycache__', 'venv', '.git'] for part in file_path.parts):
                continue

            if not file_path.is_file():
                continue

            try:
                rel_path = str(file_path.relative_to(self.working_dir))
                filename = file_path.name
                files.append((rel_path, filename))
                count += 1
            except ValueError:
                continue

        self._file_cache = files

        with open("/tmp/clio_debug.log", "a") as f:
            f.write(f"[CACHE] Built cache with {len(files)} files\n")
            calc_files = [f for f in files if 'calc' in f[1].lower()]
            f.write(f"[CACHE] Files with 'calc': {calc_files}\n")

        return files

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

    def get_matches(self, target_state, candidates, search_string):
        """Override to skip default fuzzy matching - we already filtered in get_candidates."""
        # We already did the filtering/matching in get_candidates(), so just return them as-is
        with open("/tmp/clio_debug.log", "a") as f:
            f.write(f"get_matches: candidates={len(candidates)}, search='{search_string}'\n")
        return candidates

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
        """Get file candidates - directory navigation OR fuzzy search."""
        # Check if @ is present
        last_at = self._find_at_position(state)

        with open("/tmp/clio_debug.log", "a") as f:
            f.write(f"get_cand: @pos={last_at}\n")

        if last_at == -1:
            return []

        text = state.text
        cursor = state.cursor_position
        full_path = text[last_at + 1:cursor]

        with open("/tmp/clio_debug.log", "a") as f:
            f.write(f"  search_term='{full_path}'\n")

        try:
            # Mode 1: Directory navigation (has / in path)
            if '/' in full_path:
                last_slash = full_path.rfind('/')
                dir_path = full_path[:last_slash]
                search_term = full_path[last_slash + 1:]

                current_dir = self.working_dir / dir_path

                if not current_dir.exists() or not current_dir.is_dir():
                    return []

                items = []
                for item in sorted(current_dir.iterdir()):
                    name = item.name
                    if name.startswith('.'):
                        continue
                    if search_term and not name.lower().startswith(search_term.lower()):
                        continue

                    if item.is_dir():
                        items.append(DropdownItem(main=f"{name}/", prefix="📁"))
                    else:
                        items.append(DropdownItem(main=name, prefix="📄"))

                return items[:15]

            # Mode 2: Fuzzy search across all files (no / in path)
            else:
                search_term = full_path

                # If empty, show current directory contents + top files
                if not search_term:
                    items = []
                    # Show directories and files in current dir
                    for item in sorted(self.working_dir.iterdir())[:15]:
                        if item.name.startswith('.'):
                            continue
                        if item.is_dir():
                            items.append(DropdownItem(main=f"{item.name}/", prefix="📁"))
                        else:
                            items.append(DropdownItem(main=item.name, prefix="📄"))

                    with open("/tmp/clio_debug.log", "a") as f:
                        f.write(f"  returning {len(items)} (all)\n")

                    return items

                # Fuzzy search all files
                all_files = self._get_all_files()
                search_lower = search_term.lower()
                matched = []

                with open("/tmp/clio_debug.log", "a") as f:
                    f.write(f"  cached files={len(all_files)}\n")

                for rel_path, filename in all_files:
                    if search_lower in filename.lower():
                        matched.append((0, DropdownItem(main=rel_path, prefix="📄")))
                    elif search_lower in rel_path.lower():
                        matched.append((1, DropdownItem(main=rel_path, prefix="📄")))

                with open("/tmp/clio_debug.log", "a") as f:
                    f.write(f"  matched={len(matched)}\n")
                    if len(matched) > 0:
                        f.write(f"  first match={matched[0][1].main}\n")

                matched.sort(key=lambda x: (x[0], x[1].value.lower()))

                with open("/tmp/clio_debug.log", "a") as f:
                    f.write(f"  returning {len(matched[:15])} (fuzzy)\n")

                return [item[1] for item in matched[:15]]

        except Exception as e:
            with open("/tmp/clio_debug.log", "a") as f:
                f.write(f"  EXCEPTION: {e}\n")
            return []

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Apply completion - preserve directory path for navigation, full path for fuzzy."""
        target = self.target
        text = state.text
        cursor = state.cursor_position

        # Find the @ position
        last_at = self._find_at_position(state)
        if last_at == -1:
            return

        full_path_after_at = text[last_at + 1:cursor]

        # If we're in directory navigation mode (has /), preserve dir path
        if '/' in full_path_after_at:
            last_slash = full_path_after_at.rfind('/')
            dir_path = full_path_after_at[:last_slash + 1]
            complete_path = dir_path + value
        else:
            # Fuzzy mode - value is already full path
            complete_path = value

        new_value = text[:last_at] + "@" + complete_path + text[cursor:]
        new_cursor_position = last_at + 1 + len(complete_path)

        with self.prevent(Input.Changed):
            target.value = new_value
            target.cursor_position = new_cursor_position

        # If completed value is a directory (ends with /), keep dropdown open
        if complete_path.endswith("/"):
            new_target_state = self._get_target_state()
            self._rebuild_options(
                new_target_state, self.get_search_string(new_target_state)
            )
        else:
            self.action_hide()
