#!/usr/bin/env python3
"""Test custom TextArea autocomplete implementation."""
from pathlib import Path


class AutocompleteHelper:
    """Helper to test autocomplete logic before integrating with UI."""

    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self.commands = ['help', 'model', 'clear', 'exit', 'files', 'add',
                        'remove', 'config', 'copy', 'export', 'history',
                        'cleanup', 'continue', 'web']

    def find_trigger_position(self, text: str, cursor_col: int, cursor_row: int) -> tuple:
        """
        Find if there's a / or @ before cursor that should trigger autocomplete.

        Returns: (trigger_char, trigger_pos, search_term) or (None, -1, "")
        """
        lines = text.split('\n')
        if cursor_row >= len(lines):
            return (None, -1, "")

        current_line = lines[cursor_row]
        before_cursor = current_line[:cursor_col]

        # Check for / at start of line
        if before_cursor.strip().startswith('/'):
            cmd = before_cursor.strip()[1:]
            if ' ' not in cmd:  # Only autocomplete command name, not args
                return ('/', 0, cmd)

        # Check for @ anywhere in line
        last_at = before_cursor.rfind('@')
        if last_at != -1:
            after_at = before_cursor[last_at + 1:]
            if ' ' not in after_at:  # Only autocomplete until space
                return ('@', last_at, after_at)

        return (None, -1, "")

    def get_command_matches(self, search_term: str) -> list:
        """Get matching commands for /search_term."""
        if not search_term:
            return self.commands

        search_lower = search_term.lower()
        # Prefix matches first
        prefix = [cmd for cmd in self.commands if cmd.startswith(search_lower)]
        # Then contains matches
        contains = [cmd for cmd in self.commands if search_lower in cmd and cmd not in prefix]

        return prefix + contains

    def get_file_matches(self, search_term: str, max_results: int = 15) -> list:
        """Get matching files/dirs for @search_term."""
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

        # Fuzzy search mode (no /)
        else:
            # Empty search - show current dir contents
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

            # Fuzzy search all files
            search_lower = search_term.lower()
            matched = []

            for file_path in self.working_dir.rglob('*'):
                # Skip hidden and common ignores
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

                    # Prioritize filename matches over path matches
                    if search_lower in filename.lower():
                        matched.append((0, ('file', filename, rel_path)))
                    elif search_lower in rel_path.lower():
                        matched.append((1, ('file', filename, rel_path)))

                    if len(matched) >= 100:  # Limit search
                        break

                except ValueError:
                    continue

            matched.sort(key=lambda x: (x[0], x[1][2]))
            return [item[1] for item in matched[:max_results]]


def test_command_autocomplete():
    """Test / command autocomplete."""
    helper = AutocompleteHelper(Path.cwd())

    print("Testing command autocomplete:")
    print("-" * 60)

    # Test 1: Empty after /
    trigger, pos, term = helper.find_trigger_position("/", 1, 0)
    print(f"Test '/': trigger={trigger}, term='{term}'")
    matches = helper.get_command_matches(term)
    print(f"  Matches: {matches[:5]}...")
    assert trigger == '/', f"Expected trigger '/', got {trigger}"
    assert len(matches) > 0, "Should have matches for empty term"

    # Test 2: Partial command
    trigger, pos, term = helper.find_trigger_position("/he", 3, 0)
    print(f"\nTest '/he': trigger={trigger}, term='{term}'")
    matches = helper.get_command_matches(term)
    print(f"  Matches: {matches}")
    assert trigger == '/', f"Expected trigger '/'"
    assert 'help' in matches, "Should match 'help'"

    # Test 3: Command with args (should not trigger)
    trigger, pos, term = helper.find_trigger_position("/help arg", 9, 0)
    print(f"\nTest '/help arg': trigger={trigger}, term='{term}'")
    assert trigger is None, "Should not trigger after space"

    print("\n✅ Command autocomplete tests passed!")


def test_file_autocomplete():
    """Test @ file autocomplete."""
    helper = AutocompleteHelper(Path.cwd())

    print("\n\nTesting file autocomplete:")
    print("-" * 60)

    # Test 1: Empty after @
    trigger, pos, term = helper.find_trigger_position("@", 1, 0)
    print(f"Test '@': trigger={trigger}, term='{term}'")
    matches = helper.get_file_matches(term)
    print(f"  Matches (first 3): {[m[2] for m in matches[:3]]}")
    assert trigger == '@', f"Expected trigger '@', got {trigger}"
    assert len(matches) > 0, "Should have matches for current dir"

    # Test 2: Fuzzy search
    trigger, pos, term = helper.find_trigger_position("@test", 5, 0)
    print(f"\nTest '@test': trigger={trigger}, term='{term}'")
    matches = helper.get_file_matches(term)
    print(f"  Matches: {[m[2] for m in matches[:5]]}")
    assert trigger == '@', f"Expected trigger '@'"

    # Test 3: Directory navigation
    trigger, pos, term = helper.find_trigger_position("@src/", 5, 0)
    print(f"\nTest '@src/': trigger={trigger}, term='{term}'")
    matches = helper.get_file_matches(term)
    print(f"  Matches: {[m[1] for m in matches[:5]]}")
    assert trigger == '@', f"Expected trigger '@'"

    # Test 4: No trigger after space
    trigger, pos, term = helper.find_trigger_position("@file test", 10, 0)
    print(f"\nTest '@file test': trigger={trigger}")
    assert trigger is None, "Should not trigger after space"

    print("\n✅ File autocomplete tests passed!")


def test_multiline():
    """Test autocomplete in multi-line text."""
    helper = AutocompleteHelper(Path.cwd())

    print("\n\nTesting multi-line text:")
    print("-" * 60)

    text = "First line\n/he\nThird line"

    # Cursor on line 1, after "/he"
    trigger, pos, term = helper.find_trigger_position(text, 3, 1)
    print(f"Line 1 '@/he': trigger={trigger}, term='{term}'")
    matches = helper.get_command_matches(term)
    print(f"  Matches: {matches}")
    assert trigger == '/', "Should detect / on second line"
    assert 'help' in matches, "Should match help"

    print("\n✅ Multi-line tests passed!")


if __name__ == "__main__":
    try:
        test_command_autocomplete()
        test_file_autocomplete()
        test_multiline()
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
